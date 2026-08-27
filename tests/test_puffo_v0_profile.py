"""Conformance tests for the constrained, registry-backed Puffo ACP profile."""
from __future__ import annotations

import argparse
import io
import json
import multiprocessing
import os
import stat
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lingtai.adapters.acp.puffo_v0 import (
    FORCED_DISABLED_CAPABILITIES,
    PuffoV0RegistryError,
    provision_runtime,
    resolve_runtime,
    revoke_runtime,
)
from lingtai.adapters.acp.server import AcpStdioServer, INVALID_PARAMS
from lingtai.agent import Agent
from lingtai.kernel.execution_workspace import ExecutionWorkspace
from lingtai.kernel.config import AgentConfig
from tests._service_helpers import make_gemini_mock_service as make_mock_service
from tests.test_deep_refresh import _make_init


class _Agent:
    def __init__(self):
        self._shutdown = None


def _frames(output: io.StringIO) -> list[dict]:
    return [json.loads(line) for line in output.getvalue().splitlines()]


def _wait_for_frames(output: io.StringIO, count: int) -> list[dict]:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        frames = _frames(output)
        if len(frames) >= count:
            return frames
        time.sleep(0.01)
    raise AssertionError(f"timed out waiting for {count} frames")


def _new_profile_server(workspace: Path) -> tuple[AcpStdioServer, io.StringIO]:
    output = io.StringIO()
    return (
        AcpStdioServer(
            _Agent(),
            io.StringIO(),
            output,
            fixed_execution_workspace=ExecutionWorkspace(workspace),
            allow_session_mcp=False,
        ),
        output,
    )


def _request(server: AcpStdioServer, request_id: int, method: str, params: dict) -> None:
    server._dispatch({
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params,
    })


def test_provisioned_runtime_resolves_only_the_canonical_local_paths(tmp_path):
    agent_dir = tmp_path / "identity"
    agent_dir.mkdir()
    (agent_dir / "init.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = tmp_path / "registry.json"

    provisioned = provision_runtime(
        "puffo-agent-7", agent_dir, workspace, registry_path=registry
    )
    resolved = resolve_runtime("puffo-agent-7", registry_path=registry)

    assert resolved == provisioned
    stored = json.loads(registry.read_text(encoding="utf-8"))
    entry = stored["runtimes"]["puffo-agent-7"]
    assert entry["mcp_servers"] == []
    assert entry["disabled_capabilities"] == sorted(FORCED_DISABLED_CAPABILITIES)


def test_registry_rejects_tampering_and_revoked_runtime(tmp_path):
    agent_dir = tmp_path / "identity"
    agent_dir.mkdir()
    (agent_dir / "init.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = tmp_path / "registry.json"
    provision_runtime("opaque-id", agent_dir, workspace, registry_path=registry)

    data = json.loads(registry.read_text(encoding="utf-8"))
    data["runtimes"]["opaque-id"]["workspace"] = str(tmp_path)
    registry.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(PuffoV0RegistryError, match="does not match"):
        resolve_runtime("opaque-id", registry_path=registry)

    provision_runtime("active-id", agent_dir, workspace, registry_path=registry)
    revoke_runtime("active-id", registry_path=registry)
    with pytest.raises(PuffoV0RegistryError, match="inactive"):
        resolve_runtime("active-id", registry_path=registry)


def test_registry_mutations_are_linearized_so_revoke_cannot_be_resurrected(
    monkeypatch, tmp_path
):
    """A stale provision snapshot must never overwrite a completed revoke."""
    import lingtai.adapters.acp.puffo_v0 as puffo_v0

    agent_dir = tmp_path / "identity"
    agent_dir.mkdir()
    (agent_dir / "init.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = tmp_path / "registry.json"
    provision_runtime("runtime-a", agent_dir, workspace, registry_path=registry)

    original_write = puffo_v0._write_registry
    provision_waiting = threading.Event()
    release_provision = threading.Event()
    revoke_write_seen = threading.Event()
    failures: list[BaseException] = []

    def controlled_write(path, data):
        entry_a = data["runtimes"].get("runtime-a", {})
        if "runtime-b" in data["runtimes"] and entry_a.get("status") == "active":
            provision_waiting.set()
            assert release_provision.wait(timeout=5)
        if entry_a.get("status") == "revoked":
            revoke_write_seen.set()
        original_write(path, data)

    monkeypatch.setattr(puffo_v0, "_write_registry", controlled_write)

    def provision() -> None:
        try:
            provision_runtime("runtime-b", agent_dir, workspace, registry_path=registry)
        except BaseException as exc:  # pragma: no cover - surfaced below
            failures.append(exc)

    def revoke() -> None:
        try:
            revoke_runtime("runtime-a", registry_path=registry)
        except BaseException as exc:  # pragma: no cover - surfaced below
            failures.append(exc)

    provision_thread = threading.Thread(target=provision)
    provision_thread.start()
    assert provision_waiting.wait(timeout=5)
    revoke_thread = threading.Thread(target=revoke)
    revoke_thread.start()

    # Without a mutation lock, revoke writes while provision is paused and the
    # stale provision snapshot subsequently resurrects runtime-a.  With the
    # lock, revoke cannot reach its write until provision releases the lock.
    revoke_write_seen.wait(timeout=0.2)
    release_provision.set()
    provision_thread.join(timeout=5)
    revoke_thread.join(timeout=5)
    assert not provision_thread.is_alive()
    assert not revoke_thread.is_alive()
    assert not failures

    data = json.loads(registry.read_text(encoding="utf-8"))
    assert data["runtimes"]["runtime-a"]["status"] == "revoked"
    assert data["runtimes"]["runtime-b"]["status"] == "active"


def test_revocation_tombstone_denies_a_stale_active_registry_snapshot(tmp_path):
    """The main registry cannot reactivate an id once its tombstone is written."""
    agent_dir = tmp_path / "identity"
    agent_dir.mkdir()
    (agent_dir / "init.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = tmp_path / "registry.json"
    provision_runtime("runtime-a", agent_dir, workspace, registry_path=registry)
    stale_active_snapshot = registry.read_text(encoding="utf-8")

    revoke_runtime("runtime-a", registry_path=registry)
    registry.write_text(stale_active_snapshot, encoding="utf-8")

    with pytest.raises(PuffoV0RegistryError, match="inactive"):
        resolve_runtime("runtime-a", registry_path=registry)


def test_missing_required_tombstone_log_fails_closed(tmp_path):
    import lingtai.adapters.acp.puffo_v0 as puffo_v0

    agent_dir = tmp_path / "identity"
    agent_dir.mkdir()
    (agent_dir / "init.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = tmp_path / "registry.json"
    provision_runtime("runtime-a", agent_dir, workspace, registry_path=registry)
    stale_active_snapshot = registry.read_text(encoding="utf-8")
    revoke_runtime("runtime-a", registry_path=registry)
    puffo_v0._revocation_log_path(registry).unlink()
    registry.write_text(stale_active_snapshot, encoding="utf-8")

    with pytest.raises(PuffoV0RegistryError, match="revocation log is unavailable"):
        resolve_runtime("runtime-a", registry_path=registry)
    with pytest.raises(PuffoV0RegistryError, match="revocation log is unavailable"):
        provision_runtime("runtime-b", agent_dir, workspace, registry_path=registry)


@pytest.mark.skipif(os.name != "posix", reason="puffo-v0 registry is POSIX-only")
def test_registry_mutation_lock_blocks_a_second_process(tmp_path):
    import lingtai.adapters.acp.puffo_v0 as puffo_v0

    agent_dir = tmp_path / "identity"
    agent_dir.mkdir()
    (agent_dir / "init.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = tmp_path / "registry.json"
    provision_runtime("runtime-a", agent_dir, workspace, registry_path=registry)

    context = multiprocessing.get_context("fork")
    provisioned = context.Event()

    def provision_in_child() -> None:
        provision_runtime("runtime-b", agent_dir, workspace, registry_path=registry)
        provisioned.set()

    with puffo_v0._registry_mutation_lock(registry):
        child = context.Process(target=provision_in_child)
        child.start()
        assert not provisioned.wait(timeout=0.2)
    child.join(timeout=5)
    assert child.exitcode == 0
    assert provisioned.is_set()
    assert resolve_runtime("runtime-b", registry_path=registry).runtime_id == "runtime-b"


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not meaningful on Windows")
def test_registry_directory_and_files_are_owner_only_even_with_a_permissive_umask(
    monkeypatch, tmp_path
):
    import lingtai.adapters.acp.puffo_v0 as puffo_v0

    agent_dir = tmp_path / "identity"
    agent_dir.mkdir()
    (agent_dir / "init.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = tmp_path / "private" / "registry.json"
    observed: dict[str, int] = {}
    original_replace = os.replace

    def inspect_temporary(source, target):
        observed["temporary"] = stat.S_IMODE(Path(source).stat().st_mode)
        original_replace(source, target)

    monkeypatch.setattr(puffo_v0.os, "replace", inspect_temporary)
    previous_umask = os.umask(0)
    try:
        provision_runtime("runtime-a", agent_dir, workspace, registry_path=registry)
    finally:
        os.umask(previous_umask)

    assert stat.S_IMODE(registry.parent.stat().st_mode) == 0o700
    assert observed["temporary"] == 0o600
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    assert stat.S_IMODE(registry.with_name(".registry.json.lock").stat().st_mode) == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX file modes are not meaningful on Windows")
def test_resolve_tightens_legacy_registry_file_and_directory_modes(tmp_path):
    agent_dir = tmp_path / "identity"
    agent_dir.mkdir()
    (agent_dir / "init.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    registry = tmp_path / "legacy" / "registry.json"
    provision_runtime("runtime-a", agent_dir, workspace, registry_path=registry)
    registry.parent.chmod(0o755)
    registry.chmod(0o644)

    assert resolve_runtime("runtime-a", registry_path=registry).runtime_id == "runtime-a"
    assert stat.S_IMODE(registry.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600


def test_profile_session_rejects_remote_workspace_and_mcp_inputs(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    server, output = _new_profile_server(workspace)
    _request(server, 1, "initialize", {"protocolVersion": 1})

    _request(server, 2, "session/new", {"cwd": str(other), "mcpServers": []})
    _request(server, 3, "session/new", {
        "cwd": str(workspace),
        "mcpServers": [{"name": "unsafe", "command": "/bin/echo", "args": [], "env": []}],
    })

    frames = _wait_for_frames(output, 3)
    assert frames[1]["error"]["code"] == INVALID_PARAMS
    assert frames[1]["error"]["message"] == "cwd must match the profile's fixed execution workspace"
    assert frames[2]["error"]["code"] == INVALID_PARAMS
    assert frames[2]["error"]["message"] == "mcpServers must be an empty array for this profile"
    server.close()


def test_profile_cli_resolves_an_opaque_id_before_composing_acp(monkeypatch, tmp_path):
    import lingtai.cli_acp as cli_acp
    from lingtai.adapters.acp.puffo_v0 import PuffoV0Runtime

    agent_dir = tmp_path / "identity"
    agent_dir.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runtime = PuffoV0Runtime("runtime-1", agent_dir, workspace, "digest")
    observed = {}
    monkeypatch.setattr(cli_acp, "resolve_runtime", lambda _id: runtime, raising=False)
    # The handler imports from the profile module after parser validation.
    monkeypatch.setattr("lingtai.adapters.acp.puffo_v0.resolve_runtime", lambda _id: runtime)
    monkeypatch.setattr(cli_acp, "run_acp", lambda directory, **kwargs: observed.update(directory=directory, **kwargs))

    cli_acp.handle_acp_command(SimpleNamespace(profile="puffo-v0", runtime_id="runtime-1", agent_dir=None))

    assert observed["directory"] == agent_dir
    assert observed["fixed_execution_workspace"].root == workspace
    assert observed["forced_disable"] == FORCED_DISABLED_CAPABILITIES


def test_profile_cli_rejects_agent_dir_instead_of_ignoring_it(capsys):
    import lingtai.cli_acp as cli_acp

    with pytest.raises(SystemExit) as exc_info:
        cli_acp.handle_acp_command(
            SimpleNamespace(profile="puffo-v0", runtime_id=None, agent_dir=Path("/tmp"))
        )
    assert exc_info.value.code == 1
    assert "puffo-v0 does not accept --agent-dir; use --runtime-id" in capsys.readouterr().err

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    cli_acp.add_acp_parser(subparsers)
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([
            "acp", "--profile", "puffo-v0", "--agent-dir", "/tmp",
            "--runtime-id", "opaque-id",
        ])
    assert exc_info.value.code == 2


def test_forced_profile_capability_denials_override_agent_defaults(tmp_path):
    agent = Agent(
        service=make_mock_service(),
        agent_name="profile-test",
        working_dir=tmp_path / "identity",
        _forced_disable=FORCED_DISABLED_CAPABILITIES,
    )
    try:
        registered = {name for name, _ in agent._capabilities}
        assert FORCED_DISABLED_CAPABILITIES.isdisjoint(registered)
        assert agent._mcp_init_specs == {}
    finally:
        agent.stop(timeout=1.0)


def test_forced_profile_capability_denials_survive_init_refresh(tmp_path):
    (tmp_path / "init.json").write_text(
        json.dumps(_make_init(capabilities={"avatar": {}, "daemon": {}, "mcp": {}})),
        encoding="utf-8",
    )
    service = MagicMock()
    service.provider = "openai"
    service.model = "gpt-4o"
    service._base_url = None
    agent = Agent(
        service,
        agent_name="profile-refresh",
        working_dir=tmp_path,
        config=AgentConfig(),
        _forced_disable=FORCED_DISABLED_CAPABILITIES,
        _from_init_boot=True,
    )
    agent._from_init_boot = False
    try:
        agent._setup_from_init()
        agent._setup_from_init()
        registered = {name for name, _ in agent._capabilities}
        assert FORCED_DISABLED_CAPABILITIES.isdisjoint(registered)
        assert agent._mcp_init_specs == {}
    finally:
        agent.stop(timeout=1.0)

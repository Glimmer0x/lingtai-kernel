"""Conformance tests for the constrained, registry-backed Puffo ACP profile."""
from __future__ import annotations

import argparse
import io
import json
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

"""Safety and usage tests for the bundled external attach diagnostic."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = (
    Path(__file__).parents[1]
    / "src/lingtai/intrinsic_skills/system-manual/reference/external-attach-diagnostic"
    / "scripts/external_attach_diagnostic.py"
)
spec = importlib.util.spec_from_file_location("external_attach_diagnostic", SCRIPT)
external_attach_diagnostic = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = external_attach_diagnostic
assert spec.loader is not None
spec.loader.exec_module(external_attach_diagnostic)


def _agent(tmp_path: Path) -> Path:
    agent = tmp_path / "agent"
    agent.mkdir()
    (agent / ".notification").mkdir()
    (agent / ".agent.heartbeat").write_text("ok", encoding="utf-8")
    return agent


def _allow_fake_macos_sample(monkeypatch, tmp_path: Path) -> None:
    sample = tmp_path / "sample"
    sample.write_text("tool", encoding="utf-8")
    sample.chmod(0o755)
    monkeypatch.setattr(external_attach_diagnostic.sys, "platform", "darwin")
    monkeypatch.setattr(external_attach_diagnostic, "SAMPLE_TOOL", sample)
    monkeypatch.setattr(external_attach_diagnostic, "process_identity", lambda pid: f"darwin:{pid}:1")
    monkeypatch.setattr(external_attach_diagnostic, "process_identity_matches", lambda pid, identity: identity == f"darwin:{pid}:1")
    monkeypatch.setattr(external_attach_diagnostic, "_find_target_run", lambda agent_dir, pid: "module")
    monkeypatch.setattr(external_attach_diagnostic, "_kernel_identity", lambda agent_dir: {"version": "test-kernel"})

    def fake_sample(argv, **kwargs):
        assert argv[:4] == [str(sample), str(int(argv[1])), str(int(argv[2])), "-file"]
        Path(argv[4]).write_text("stack frame only\n", encoding="utf-8")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(external_attach_diagnostic.subprocess, "run", fake_sample)


def test_kernel_identity_uses_imported_runtime_source_not_agent_repo(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path)
    kernel_source = tmp_path / "kernel-source"
    observed: dict[str, Path] = {}

    class RevisionPort:
        def __init__(self, directory: Path):
            observed["directory"] = Path(directory)

    monkeypatch.setattr(external_attach_diagnostic, "PosixGitCliAdapter", RevisionPort)
    monkeypatch.setattr(external_attach_diagnostic, "_source_root", lambda _module_path: kernel_source)
    monkeypatch.setattr(
        external_attach_diagnostic,
        "runtime_identity",
        lambda _port: {"version": "test", "git_commit": "bf344c9f", "git_dirty": False},
    )

    identity = external_attach_diagnostic._kernel_identity(agent)

    assert observed["directory"] == kernel_source
    assert observed["directory"] != agent
    assert identity == {"version": "test", "git_commit": "bf344c9f", "git_dirty": False}


@pytest.mark.parametrize(
    ("identity_matches", "error"),
    ((True, None), (False, "changed incarnation")),
    ids=("canonical-agent-match", "incarnation-changed"),
)
def test_target_binding_requires_canonical_live_agent_and_stable_incarnation(
    tmp_path: Path, monkeypatch, identity_matches: bool, error: str | None
):
    agent = _agent(tmp_path)

    class Scan:
        def iter_process_commands(self):
            yield 4242, f"/usr/bin/python3 -m lingtai run {agent}"

    monkeypatch.setattr(external_attach_diagnostic, "PosixAgentProcessScanAdapter", Scan)
    monkeypatch.setattr(external_attach_diagnostic, "process_identity", lambda _pid: "incarnation-a")
    monkeypatch.setattr(
        external_attach_diagnostic,
        "process_identity_matches",
        lambda _pid, identity: identity_matches and identity == "incarnation-a",
    )
    if error:
        with pytest.raises(external_attach_diagnostic.DiagnosticError, match=error):
            external_attach_diagnostic._observe_target(agent, 4242)
        return

    observed = external_attach_diagnostic._observe_target(agent, 4242)
    assert (observed.run_form, observed.start_identity) == ("module", "incarnation-a")
    with pytest.raises(external_attach_diagnostic.DiagnosticError, match="not a live LingTai run"):
        external_attach_diagnostic._observe_target(tmp_path / "different-agent", 4242)


def _arguments(agent: Path, artifact: Path, *extra: str) -> list[str]:
    return ["--agent-dir", str(agent), "--pid", "4242", "--artifact-dir", str(artifact), *extra]


def test_unsupported_host_refuses_before_artifact_directory_side_effect(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path)
    artifact = tmp_path / "must-not-exist"
    monkeypatch.setattr(external_attach_diagnostic.sys, "platform", "linux")

    assert external_attach_diagnostic.main(_arguments(agent, artifact)) == 1
    assert not artifact.exists()


def test_default_capture_is_content_free_agent_read_only_and_labels_stacks(tmp_path: Path, monkeypatch):
    agent = _agent(tmp_path)
    # These deliberately sensitive-looking bodies must never be parsed/copied.
    (agent / ".notification" / "system.json").write_text('{"body":"do-not-copy-abc123"}', encoding="utf-8")
    (agent / "system").mkdir()
    (agent / "system" / "prompt.md").write_text("do-not-copy-prompt-xyz", encoding="utf-8")
    _allow_fake_macos_sample(monkeypatch, tmp_path)
    artifact = tmp_path / "capture"

    assert external_attach_diagnostic.main(_arguments(agent, artifact, "--related-pid", "4243")) == 0
    evidence_text = (artifact / "evidence.json").read_text(encoding="utf-8")
    evidence = json.loads(evidence_text)
    assert (artifact / "pid-4242.stack.txt").read_text(encoding="utf-8") == "stack frame only\n"
    assert (artifact / "related-pid-4243.stack.txt").is_file()
    assert evidence["interpretation"] == "Stacks only; not semantic stage timings."
    assert evidence["safe_counts"]["notification_json_files"] == 1
    assert evidence["controlled_burst"] == {
        "requested": False,
        "cleanup_requested": False,
        "target_filename": None,
        "store_locking_exercised": False,
    }
    assert "darwin:4242:1" not in evidence_text
    assert "do-not-copy-abc123" not in evidence_text
    assert "do-not-copy-prompt-xyz" not in evidence_text
    assert not list((agent / ".notification").glob("mcp.external-attach-diagnostic.*.json"))


@pytest.mark.parametrize("target_exists", (False, True), ids=("claim-and-cleanup", "existing-target-refuses"))
def test_controlled_burst_claim_is_exclusive_and_cleanup_is_exact_run_id_only(
    tmp_path: Path, monkeypatch, target_exists: bool
):
    agent = _agent(tmp_path)
    _allow_fake_macos_sample(monkeypatch, tmp_path)
    unrelated = agent / ".notification" / "mcp.unrelated.json"
    unrelated.write_text("keep", encoding="utf-8")
    run_id = "existing-a" if target_exists else "incident-20260824-a"
    target = agent / ".notification" / f"mcp.external-attach-diagnostic.{run_id}.json"
    if target_exists:
        target.write_text("foreign-content", encoding="utf-8")

    artifact = tmp_path / ("must-not-exist" if target_exists else "capture-create")
    result = external_attach_diagnostic.main(
        _arguments(agent, artifact, "--controlled-burst", "--burst-run-id", run_id)
    )
    if target_exists:
        assert result == 1
        assert target.read_text(encoding="utf-8") == "foreign-content"
        assert not artifact.exists()
        return

    assert result == 0
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["data"] == {
        "kind": "external_attach_controlled_burst",
        "diagnostic_run_id": run_id,
        "content_free": True,
    }
    assert unrelated.read_text(encoding="utf-8") == "keep"
    assert external_attach_diagnostic.main(
        _arguments(agent, tmp_path / "capture-clean", "--cleanup-controlled-burst", "--burst-run-id", run_id)
    ) == 0
    assert not target.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"

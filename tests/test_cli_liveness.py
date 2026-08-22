import json
import sys

from lingtai.kernel import session_stats


def _run_cli(monkeypatch, argv: list[str]) -> int:
    from lingtai.cli import main

    monkeypatch.setattr(sys, "argv", ["lingtai-agent", *argv])
    try:
        main()
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


def _record(state: str, heartbeat_at: float) -> dict:
    return {
        "schema": session_stats.AGENT_RECORD_SCHEMA,
        "schema_version": session_stats.AGENT_RECORD_VERSION,
        "session": {"state": state},
        "health": {"heartbeat_at": heartbeat_at, "liveness": "fresh"},
    }


def test_liveness_cli_emits_only_kernel_owned_liveness_dict(tmp_path, monkeypatch, capsys):
    session_stats.write_agent_record(tmp_path, _record("active", 100.0))
    before = session_stats.agent_record_path(tmp_path).read_bytes()
    monkeypatch.setattr("lingtai.cli.time.time", lambda: 100.0)

    assert _run_cli(monkeypatch, ["liveness", "--agent-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"liveness": "active"}
    assert session_stats.agent_record_path(tmp_path).read_bytes() == before


def test_liveness_cli_degrades_to_unavailable_without_legacy_fallback(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("lingtai.cli.time.time", lambda: 100.0)

    assert _run_cli(monkeypatch, ["liveness", "--agent-dir", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"liveness": "unavailable"}


def test_liveness_cli_rejects_a_non_directory(monkeypatch, capsys, tmp_path):
    missing = tmp_path / "missing"

    assert _run_cli(monkeypatch, ["liveness", "--agent-dir", str(missing)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "is not a directory" in captured.err

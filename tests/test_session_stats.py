"""Contract tests for the Agent Record / daemon self-record (kernel.session_stats).

Covers: atomic publication, schema/version/freshness, redaction, the
per-turn daemon self-record writer, bounded present-only aggregation, and the
migrated Telegram/local-commands consumer paths.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.kernel import _fsutil, session_stats
from lingtai.kernel.base_agent import BaseAgent
from lingtai.kernel.state import AgentState


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self, wall: float = 1000.0, mono: float = 100.0):
        self._wall = wall
        self._mono = mono

    def wall_seconds(self) -> float:
        return self._wall

    def monotonic_seconds(self) -> float:
        return self._mono


def _stub_agent(tmp_path: Path, **overrides) -> SimpleNamespace:
    defaults = dict(
        _agent_id="agent-123",
        agent_name="真名",
        nickname="小明",
        _mail_service=None,
        _lifecycle_clock=_FakeClock(),
        _started_at="2026-08-20T00:00:00Z",
        _uptime_anchor=90.0,
        _heartbeat=999.0,
        _molt_count=2,
        _chat=None,
        _config=SimpleNamespace(context_limit=None),
        _state=AgentState.ACTIVE,
        _working_dir=tmp_path,
        _last_api_call_at=995.0,
        _last_progress_at=990.0,
        service=None,
        get_token_usage=lambda: {
            "input_tokens": 10, "output_tokens": 5, "thinking_tokens": 1,
            "cached_tokens": 2, "total_tokens": 16, "api_calls": 3,
            "ctx_system_tokens": 100, "ctx_tools_tokens": 50,
            "ctx_history_tokens": 25, "ctx_total_tokens": 175,
        },
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _daemon_state(**overrides) -> dict:
    state = {
        "run_id": "em-abcd", "handle": "em-abcd", "group_id": "dg-1",
        "backend": "lingtai", "state": "running",
        "started_at": "2026-08-20T00:00:00Z", "finished_at": None,
        "turn": 3, "tool_call_count": 5,
        "tokens": {"input": 40, "output": 20, "thinking": 0, "cached": 5},
        "cli_tokens": {"input": 0, "output": 0, "thinking": 0, "cached": 0, "calls": 0},
    }
    state.update(overrides)
    return state


# ---------------------------------------------------------------------------
# Agent record — schema / atomic write / redaction
# ---------------------------------------------------------------------------


def test_agent_record_schema_version_and_generated_at(tmp_path):
    record = session_stats.build_agent_record(_stub_agent(tmp_path))
    assert record["schema"] == session_stats.AGENT_RECORD_SCHEMA
    assert record["schema_version"] == session_stats.AGENT_RECORD_VERSION
    assert record["generated_at"].endswith("Z")
    assert record["sequence"] == 0


def test_agent_record_never_contains_working_dir_path(tmp_path):
    secret_marker = str(tmp_path)
    record = session_stats.build_agent_record(_stub_agent(tmp_path))
    dumped = json.dumps(record)
    assert secret_marker not in dumped


def test_agent_record_identity_and_usage_fields(tmp_path):
    record = session_stats.build_agent_record(_stub_agent(tmp_path))
    assert record["identity"]["agent_id"] == "agent-123"
    assert record["identity"]["agent_name"] == "真名"
    assert record["identity"]["nickname"] == "小明"
    assert record["session"]["state"] == "active"
    assert record["session"]["molt_count"] == 2
    assert record["usage"]["input_tokens"] == 10
    assert record["usage"]["api_calls"] == 3
    assert record["usage"]["context_used_tokens"] == 175
    assert record["health"]["last_api_call_at"] == 995.0
    assert record["health"]["last_progress_at"] == 990.0


def test_agent_record_liveness_fresh_vs_stale(tmp_path):
    fresh = session_stats.build_agent_record(
        _stub_agent(tmp_path, _lifecycle_clock=_FakeClock(wall=1000.0), _heartbeat=999.0)
    )
    assert fresh["health"]["liveness"] == "fresh"

    stale = session_stats.build_agent_record(
        _stub_agent(tmp_path, _lifecycle_clock=_FakeClock(wall=1100.0), _heartbeat=999.0)
    )
    assert stale["health"]["liveness"] == "stale"

    unknown = session_stats.build_agent_record(_stub_agent(tmp_path, _heartbeat=0.0))
    assert unknown["health"]["liveness"] == "unknown"


def test_agent_record_extra_hook_merges_handles_and_integrations(tmp_path):
    agent = _stub_agent(tmp_path)
    agent._build_agent_record_extra = lambda: {
        "handles": {"telegram": "botuser"},
        "integrations": [{"name": "telegram", "transport": "stdio", "connected": True}],
    }
    record = session_stats.build_agent_record(agent)
    assert record["handles"] == {"telegram": "botuser"}
    assert record["integrations"] == [{"name": "telegram", "transport": "stdio", "connected": True}]


def test_agent_record_extra_hook_failure_is_swallowed(tmp_path):
    agent = _stub_agent(tmp_path)

    def _boom():
        raise RuntimeError("mcp registry unavailable")

    agent._build_agent_record_extra = _boom
    record = session_stats.build_agent_record(agent)
    assert record["handles"] == {}
    assert record["integrations"] == []


def test_write_agent_record_is_atomic(tmp_path, monkeypatch):
    replacements = []
    real_replace = _fsutil.os.replace

    def spy_replace(src, dst):
        replacements.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(_fsutil.os, "replace", spy_replace)

    record = session_stats.build_agent_record(_stub_agent(tmp_path))
    path = session_stats.write_agent_record(tmp_path, record)

    assert path == tmp_path / "system" / "agent_record.json"
    assert len(replacements) == 1
    temp_path, replaced_target = map(Path, replacements[0])
    assert temp_path.parent == path.parent
    assert replaced_target == path
    assert session_stats.read_agent_record(tmp_path) == record


def test_read_agent_record_missing_and_corrupt_return_none(tmp_path):
    assert session_stats.read_agent_record(tmp_path) is None
    path = session_stats.agent_record_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("not json", encoding="utf-8")
    assert session_stats.read_agent_record(tmp_path) is None


# ---------------------------------------------------------------------------
# Published Agent Record lifecycle classification
# ---------------------------------------------------------------------------


def _published_agent_record(state: str, health: dict) -> dict:
    return {
        "schema": session_stats.AGENT_RECORD_SCHEMA,
        "schema_version": session_stats.AGENT_RECORD_VERSION,
        "session": {"state": state},
        "health": health,
    }


def test_published_agent_record_liveness_boundary_is_strict():
    heartbeat_at = 100.0
    record = _published_agent_record("active", {
        "heartbeat_at": heartbeat_at,
        "liveness": "fresh",
    })

    assert session_stats.classify_published_agent_record(
        record,
        wall_now=heartbeat_at + session_stats.HEARTBEAT_LIVENESS_SECONDS - 0.001,
    ) == "active"
    assert session_stats.classify_published_agent_record(
        record,
        wall_now=heartbeat_at + session_stats.HEARTBEAT_LIVENESS_SECONDS,
    ) == "offline"


@pytest.mark.parametrize("health", [
    {"liveness": "fresh"},
    {"heartbeat_at": float("nan"), "liveness": "fresh"},
    {"heartbeat_at": float("inf"), "liveness": "fresh"},
])
def test_published_agent_record_missing_or_nonfinite_heartbeat_is_offline(health):
    assert session_stats.classify_published_agent_record(
        _published_agent_record("idle", health), wall_now=100.0,
    ) == "offline"


@pytest.mark.parametrize("state", ["stuck", "suspended"])
def test_published_agent_record_keeps_explicit_terminal_state(state):
    assert session_stats.classify_published_agent_record(
        _published_agent_record(state, {"heartbeat_at": 0.0}), wall_now=10_000.0,
    ) == state


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (_published_agent_record("active", {"heartbeat_at": 100.0}), "active"),
        (_published_agent_record("idle", {"heartbeat_at": 90.0}), "offline"),
        (_published_agent_record("stuck", {"heartbeat_at": 0.0}), "stuck"),
        (_published_agent_record("suspended", {"heartbeat_at": 0.0}), "suspended"),
        ({}, "unavailable"),
    ],
)
def test_query_published_agent_liveness_is_the_complete_consumer_dict(record, expected):
    assert session_stats.query_published_agent_liveness(
        record,
        wall_now=100.0,
    ) == {"liveness": expected}


# ---------------------------------------------------------------------------
# should_refresh_agent_record / env var validation
# ---------------------------------------------------------------------------


def test_should_refresh_agent_record_first_write_always_refreshes():
    assert session_stats.should_refresh_agent_record(None, 100.0, 5.0) is True


def test_should_refresh_agent_record_throttles_within_window():
    assert session_stats.should_refresh_agent_record(100.0, 102.0, 5.0) is False
    assert session_stats.should_refresh_agent_record(100.0, 105.0, 5.0) is True


def test_should_refresh_agent_record_wall_clock_regression_refreshes():
    assert session_stats.should_refresh_agent_record(200.0, 100.0, 5.0) is True


@pytest.mark.parametrize("raw", [None, "", "  ", "not-a-number", "0", "-1", "nan", "inf"])
def test_session_stats_refresh_seconds_falls_back(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv(session_stats.REFRESH_SECONDS_ENV, raising=False)
    else:
        monkeypatch.setenv(session_stats.REFRESH_SECONDS_ENV, raw)
    assert session_stats.session_stats_refresh_seconds() == session_stats.DEFAULT_REFRESH_SECONDS


def test_session_stats_refresh_seconds_accepts_valid_value(monkeypatch):
    monkeypatch.setenv(session_stats.REFRESH_SECONDS_ENV, "12.5")
    assert session_stats.session_stats_refresh_seconds() == 12.5


@pytest.mark.parametrize("raw", [None, "", "  ", "not-an-int", "0", "-5", "3.5"])
def test_session_stats_daemon_limit_falls_back(monkeypatch, raw):
    if raw is None:
        monkeypatch.delenv(session_stats.DAEMON_LIMIT_ENV, raising=False)
    else:
        monkeypatch.setenv(session_stats.DAEMON_LIMIT_ENV, raw)
    assert session_stats.session_stats_daemon_limit() == session_stats.DEFAULT_DAEMON_LIMIT


def test_session_stats_daemon_limit_accepts_valid_value(monkeypatch):
    monkeypatch.setenv(session_stats.DAEMON_LIMIT_ENV, "7")
    assert session_stats.session_stats_daemon_limit() == 7


# ---------------------------------------------------------------------------
# BaseAgent._write_session_stats_record — throttled, best-effort hook
# ---------------------------------------------------------------------------


def test_write_session_stats_record_writes_on_first_call(tmp_path):
    agent = _stub_agent(tmp_path)
    agent._session_stats_last_written_at = None
    agent._session_stats_sequence = 0

    BaseAgent._write_session_stats_record(agent)

    record = session_stats.read_agent_record(tmp_path)
    assert record is not None
    assert record["sequence"] == 1
    assert agent._session_stats_last_written_at == 1000.0


def test_write_session_stats_record_throttled_within_window(tmp_path, monkeypatch):
    monkeypatch.setenv(session_stats.REFRESH_SECONDS_ENV, "5")
    agent = _stub_agent(tmp_path, _lifecycle_clock=_FakeClock(wall=1000.0))
    agent._session_stats_last_written_at = 998.0
    agent._session_stats_sequence = 0

    BaseAgent._write_session_stats_record(agent)

    assert session_stats.read_agent_record(tmp_path) is None
    assert agent._session_stats_sequence == 0


def test_write_session_stats_record_failure_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    agent = _stub_agent(tmp_path)
    agent._session_stats_last_written_at = None
    agent._session_stats_sequence = 0

    def _boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(session_stats, "write_agent_record", _boom)
    with caplog.at_level(logging.WARNING):
        BaseAgent._write_session_stats_record(agent)  # must not raise
    assert "Failed to write agent record" in caplog.text


# ---------------------------------------------------------------------------
# Daemon self-record — schema / atomic write / redaction
# ---------------------------------------------------------------------------


def test_daemon_record_schema_and_bounded_fields(tmp_path):
    record = session_stats.build_daemon_record(_daemon_state())
    assert record["schema"] == session_stats.DAEMON_RECORD_SCHEMA
    assert record["schema_version"] == session_stats.DAEMON_RECORD_VERSION
    assert record["run_id"] == "em-abcd"
    assert record["state"] == "running"
    assert record["tokens"] == {"input": 40, "output": 20, "thinking": 0, "cached": 5}
    assert record["cli_tokens"]["calls"] == 0


def test_daemon_record_never_carries_task_text_or_errors(tmp_path):
    state = _daemon_state(
        task="do something with /secret/path and API_KEY=xyz",
        error={"type": "RuntimeError", "message": "leaked /secret/path"},
        call_parameters={"task": "..."},
    )
    record = session_stats.build_daemon_record(state)
    dumped = json.dumps(record)
    assert "secret" not in dumped
    assert "error" not in record
    assert "task" not in record
    assert "call_parameters" not in record


def test_write_daemon_record_is_atomic(tmp_path, monkeypatch):
    replacements = []
    real_replace = _fsutil.os.replace

    def spy_replace(src, dst):
        replacements.append((src, dst))
        return real_replace(src, dst)

    monkeypatch.setattr(_fsutil.os, "replace", spy_replace)

    run_dir = tmp_path / "daemons" / "em-abcd"
    run_dir.mkdir(parents=True)
    path = session_stats.write_daemon_record(run_dir, _daemon_state())

    assert path == run_dir / session_stats.DAEMON_RECORD_FILENAME
    assert len(replacements) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["run_id"] == "em-abcd"


# ---------------------------------------------------------------------------
# aggregate_daemon_records — bounded, newest-first, present-only
# ---------------------------------------------------------------------------


def _write_daemon_record_at(daemons_dir: Path, run_id: str, **overrides) -> None:
    run_dir = daemons_dir / run_id
    run_dir.mkdir(parents=True)
    session_stats.write_daemon_record(run_dir, _daemon_state(run_id=run_id, **overrides))


def test_aggregate_daemon_records_empty_when_no_daemons_dir(tmp_path):
    agg = session_stats.aggregate_daemon_records(tmp_path)
    assert agg == {
        "present": 0, "scanned": 0, "limit": session_stats.DEFAULT_DAEMON_LIMIT,
        "counts_by_state": {}, "usage": session_stats._empty_daemon_usage_totals(),
    }


def test_aggregate_daemon_records_none_working_dir_is_honest_zero():
    agg = session_stats.aggregate_daemon_records(None)
    assert agg["present"] == 0
    assert agg["scanned"] == 0


def test_aggregate_daemon_records_ignores_daemons_without_self_record(tmp_path):
    daemons_dir = tmp_path / "daemons"
    daemons_dir.mkdir()
    # A daemon that only has daemon.json (legacy / not yet turned) — must be
    # ignored entirely, never backfilled or shown as a zero entry.
    legacy = daemons_dir / "em-legacy"
    legacy.mkdir()
    (legacy / "daemon.json").write_text(json.dumps({"run_id": "em-legacy", "state": "running"}))

    _write_daemon_record_at(daemons_dir, "em-fresh", state="done")

    agg = session_stats.aggregate_daemon_records(tmp_path)
    assert agg["present"] == 1
    assert agg["scanned"] == 1
    assert agg["counts_by_state"] == {"done": 1}


def test_aggregate_daemon_records_sums_usage_across_present_records(tmp_path):
    daemons_dir = tmp_path / "daemons"
    daemons_dir.mkdir()
    _write_daemon_record_at(
        daemons_dir, "em-1", state="running",
        tokens={"input": 10, "output": 5, "thinking": 0, "cached": 0},
        cli_tokens={"input": 0, "output": 0, "thinking": 0, "cached": 0, "calls": 0},
    )
    _write_daemon_record_at(
        daemons_dir, "em-2", state="done",
        tokens={"input": 0, "output": 0, "thinking": 0, "cached": 0},
        cli_tokens={"input": 20, "output": 8, "thinking": 0, "cached": 2, "calls": 3},
    )

    agg = session_stats.aggregate_daemon_records(tmp_path)
    assert agg["present"] == 2
    assert agg["scanned"] == 2
    assert agg["counts_by_state"] == {"running": 1, "done": 1}
    assert agg["usage"] == {
        "input_tokens": 30, "output_tokens": 13, "thinking_tokens": 0,
        "cached_tokens": 2, "api_calls": 3,
    }


def test_aggregate_daemon_records_bounded_to_limit_newest_first(tmp_path, monkeypatch):
    import time as time_module

    daemons_dir = tmp_path / "daemons"
    daemons_dir.mkdir()
    for i in range(5):
        _write_daemon_record_at(daemons_dir, f"em-{i}")
        # Force distinct mtimes so newest-first ordering is deterministic
        # across fast filesystems with coarse mtime resolution.
        path = daemons_dir / f"em-{i}" / session_stats.DAEMON_RECORD_FILENAME
        stamp = time_module.time() + i
        import os as os_module
        os_module.utime(path, (stamp, stamp))

    agg = session_stats.aggregate_daemon_records(tmp_path, limit=2)
    assert agg["present"] == 5
    assert agg["scanned"] == 2


def test_aggregate_daemon_records_skips_corrupt_record(tmp_path):
    daemons_dir = tmp_path / "daemons"
    daemons_dir.mkdir()
    bad = daemons_dir / "em-bad"
    bad.mkdir()
    (bad / session_stats.DAEMON_RECORD_FILENAME).write_text("not json")

    _write_daemon_record_at(daemons_dir, "em-good")

    agg = session_stats.aggregate_daemon_records(tmp_path)
    assert agg["present"] == 2
    assert agg["scanned"] == 1

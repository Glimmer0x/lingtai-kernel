# tests/test_daemon_cli_watchdog_scope.py
"""Regression tests for parent-process CLI proc tracking.

Every emanation now runs under its own detached supervisor, whose
``_control_and_deadline_watcher`` (see supervisor_runtime.py) enforces the
per-run timeout and kills only that run's own exact child — there is no
shared parent-process batch watchdog left to scope. These tests cover what
remains live in the parent manager: ``_register_cli_proc``/
``_unregister_cli_proc`` tracking and reclaim-all killing every tracked proc.
"""
from unittest.mock import MagicMock

from lingtai.kernel.config import AgentConfig


class _FakeProc:
    """A stand-in for subprocess.Popen the kill helper can record against."""

    _next_pid = 9000

    def __init__(self):
        type(self)._next_pid += 1
        self.pid = type(self)._next_pid
        self.killed = False

    def wait(self, timeout=None):
        return 0


def _make_manager(tmp_path):
    from lingtai.agent import Agent

    svc = MagicMock()
    svc.provider = "mock"
    svc.model = "mock-model"
    svc.create_session = MagicMock()
    svc.make_tool_result = MagicMock()
    agent = Agent(
        svc,
        working_dir=tmp_path / "daemon-agent",
        capabilities=["daemon"],
        config=AgentConfig(),
    )
    return agent.get_capability("daemon")


def test_reclaim_all_kills_every_tracked_proc(tmp_path, monkeypatch):
    """Reclaim-all / agent stop still kills all tracked CLI procs."""
    mgr = _make_manager(tmp_path)

    killed: list = []
    monkeypatch.setattr(
        "lingtai.tools.daemon._kill_process_group",
        lambda proc: killed.append(proc),
    )

    p_a = _FakeProc()
    p_b = _FakeProc()
    p_ask = _FakeProc()
    mgr._register_cli_proc(p_a, group_id="group-a")
    mgr._register_cli_proc(p_b, group_id="group-b")
    mgr._register_cli_proc(p_ask, group_id=None)  # ask procs: no batch group

    report = mgr._handle_reclaim()

    assert report["status"] == "reclaimed"
    assert set(killed) == {p_a, p_b, p_ask}
    assert mgr._cli_procs == []
    assert mgr._cli_proc_groups == {}


def test_unregister_removes_from_group_and_global(tmp_path):
    """Normal completion detaches a proc from both global and group tracking."""
    mgr = _make_manager(tmp_path)

    proc = _FakeProc()
    mgr._register_cli_proc(proc, group_id="group-x")
    assert proc in mgr._cli_procs
    assert proc in mgr._cli_proc_groups["group-x"]

    mgr._unregister_cli_proc(proc, group_id="group-x")
    assert proc not in mgr._cli_procs
    # Empty group buckets are pruned so they don't leak across runs.
    assert "group-x" not in mgr._cli_proc_groups

    # Idempotent: a second unregister (e.g. after reclaim already drained it)
    # must not raise.
    mgr._unregister_cli_proc(proc, group_id="group-x")

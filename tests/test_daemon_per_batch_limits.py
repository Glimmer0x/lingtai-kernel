"""Tests for per-batch max_turns and timeout overrides on daemon.emanate."""
from tests._daemon_helpers import (
    install_fake_detached_owner,
    make_daemon_agent as _make_agent,
    wait_daemon_terminal,
)


def test_emanate_default_uses_ceiling(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path, ["file", "daemon"])
    mgr = agent.get_capability("daemon")
    records = install_fake_detached_owner(monkeypatch)

    out = mgr.handle({
        "action": "emanate",
        "input": {
            "tasks": [
                {
                    "task": "x",
                    "tools": ['file'],
                },
            ],
        },
    })

    assert out["status"] == "dispatched"
    state = wait_daemon_terminal(records[0]["run_dir"])
    assert mgr._max_turns == 1000
    assert records[0]["manifest"]["max_turns"] == 1000
    assert state["max_turns"] == 1000



def test_daemon_schema_advertises_1000_turn_ceiling():
    from lingtai.tools.daemon import get_schema

    max_turns_schema = next(
        branch for branch in get_schema("en")["properties"]["input"]["anyOf"]
        if branch["title"] == "emanate input"
    )["properties"]["max_turns"]
    assert max_turns_schema["minimum"] == 1
    assert max_turns_schema["maximum"] == 1000
    assert "1000" in max_turns_schema["description"]

def test_emanate_respects_per_batch_max_turns(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path, ["file", "daemon"])
    mgr = agent.get_capability("daemon")
    records = install_fake_detached_owner(monkeypatch)

    out = mgr.handle({
        "action": "emanate",
        "input": {
            "max_turns": 50,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['file'],
                },
            ],
        },
    })

    assert out["status"] == "dispatched"
    state = wait_daemon_terminal(records[0]["run_dir"])
    assert records[0]["manifest"]["max_turns"] == 50
    assert state["max_turns"] == 50


def test_emanate_caps_max_turns_at_ceiling(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path, ["file", "daemon"])
    mgr = agent.get_capability("daemon")
    records = install_fake_detached_owner(monkeypatch)

    # ceiling is 1000; ask for 9999
    out = mgr.handle({
        "action": "emanate",
        "input": {
            "max_turns": 9999,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['file'],
                },
            ],
        },
    })

    assert out["status"] == "dispatched"
    state = wait_daemon_terminal(records[0]["run_dir"])
    assert mgr._max_turns == 1000
    assert records[0]["manifest"]["max_turns"] == 1000
    assert state["max_turns"] == 1000


def test_emanate_allows_new_1000_turn_ceiling(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path, ["file", "daemon"])
    mgr = agent.get_capability("daemon")
    records = install_fake_detached_owner(monkeypatch)

    out = mgr.handle({
        "action": "emanate",
        "input": {
            "max_turns": 1000,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['file'],
                },
            ],
        },
    })

    assert out["status"] == "dispatched"
    state = wait_daemon_terminal(records[0]["run_dir"])
    assert records[0]["manifest"]["max_turns"] == 1000
    assert state["max_turns"] == 1000


def test_emanate_rejects_zero_max_turns(tmp_path):
    agent = _make_agent(tmp_path, ["daemon"])
    mgr = agent.get_capability("daemon")
    out = mgr.handle({
        "action": "emanate",
        "input": {
            "max_turns": 0,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['read'],
                },
            ],
        },
    })
    assert out["status"] == "error"
    assert "max_turns" in out["message"]


def test_emanate_rejects_negative_max_turns(tmp_path):
    agent = _make_agent(tmp_path, ["daemon"])
    mgr = agent.get_capability("daemon")
    out = mgr.handle({
        "action": "emanate",
        "input": {
            "max_turns": -5,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['read'],
                },
            ],
        },
    })
    assert out["status"] == "error"
    assert "max_turns" in out["message"]


def test_emanate_respects_per_batch_timeout(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path, ["file", "daemon"])
    mgr = agent.get_capability("daemon")
    records = install_fake_detached_owner(monkeypatch)

    out = mgr.handle({
        "action": "emanate",
        "input": {
            "timeout": 600,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['file'],
                },
            ],
        },
    })

    assert out["status"] == "dispatched"
    wait_daemon_terminal(records[0]["run_dir"])
    assert records[0]["manifest"]["timeout_s"] == 600.0


def test_emanate_caps_timeout_at_ceiling(tmp_path, monkeypatch):
    agent = _make_agent(tmp_path, ["file", "daemon"])
    mgr = agent.get_capability("daemon")
    records = install_fake_detached_owner(monkeypatch)

    out = mgr.handle({
        "action": "emanate",
        "input": {
            "timeout": 99999,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['file'],
                },
            ],
        },
    })

    assert out["status"] == "dispatched"
    wait_daemon_terminal(records[0]["run_dir"])
    assert records[0]["manifest"]["timeout_s"] == mgr._timeout


def test_emanate_rejects_zero_timeout(tmp_path):
    agent = _make_agent(tmp_path, ["daemon"])
    mgr = agent.get_capability("daemon")
    out = mgr.handle({
        "action": "emanate",
        "input": {
            "timeout": 0,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['read'],
                },
            ],
        },
    })
    assert out["status"] == "error"
    assert "timeout" in out["message"]


def test_emanate_rejects_negative_timeout(tmp_path):
    agent = _make_agent(tmp_path, ["daemon"])
    mgr = agent.get_capability("daemon")
    out = mgr.handle({
        "action": "emanate",
        "input": {
            "timeout": -1,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['read'],
                },
            ],
        },
    })
    assert out["status"] == "error"
    assert "timeout" in out["message"]


def test_emanate_rejects_sub_5s_timeout(tmp_path):
    """Sub-5s timeouts can fire before the emanation thread starts (the
    watchdog ticks at 1s and OS scheduling can delay its first run).
    Refuse rather than silently mark emanations as 'timeout' before they ran."""
    agent = _make_agent(tmp_path, ["daemon"])
    mgr = agent.get_capability("daemon")
    out = mgr.handle({
        "action": "emanate",
        "input": {
            "timeout": 2,
            "tasks": [
                {
                    "task": "x",
                    "tools": ['read'],
                },
            ],
        },
    })
    assert out["status"] == "error"
    assert "timeout" in out["message"]
    assert "5" in out["message"]

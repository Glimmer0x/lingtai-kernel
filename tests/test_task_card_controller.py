"""Focused coverage for the intrinsic declarative ``task_card`` capability."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from lingtai.tools.task_card import TaskCardManager, get_description, get_schema, setup


class _FakeAgent:
    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self._shutdown = threading.Event()
        self.wakes: list[dict] = []
        self.added_tools: list[tuple] = []

    def _enqueue_system_notification(self, **kwargs):
        self.wakes.append(kwargs)
        return "notif-id"

    def add_tool(
        self,
        name,
        *,
        schema=None,
        handler=None,
        description="",
        glossary_package="__unset__",
        **_,
    ):
        self.added_tools.append((name, schema, handler, description, glossary_package))


def _write_renderer(workdir: Path, body: str, name: str = "renderer.py") -> str:
    path = workdir / name
    path.write_text(body, encoding="utf-8")
    return str(path)


_OK_BODY = "print('# Task Card\\n\\n- first\\n- second')"


@pytest.fixture
def agent(tmp_path):
    return _FakeAgent(tmp_path)


@pytest.fixture
def manager(agent):
    value = TaskCardManager(agent)
    yield value
    value.shutdown_for_agent_stop()


def test_setup_registers_the_intrinsic_task_card_tool(agent):
    mgr = setup(agent)
    assert isinstance(mgr, TaskCardManager)
    name, schema, handler, description, glossary = agent.added_tools[0]
    assert name == "task_card"
    assert schema == get_schema()
    assert description == get_description()
    assert glossary is None
    assert callable(handler)


def test_description_routes_to_manual_and_file_contract():
    desc = get_description()
    assert "taskcard/status" in desc
    assert "taskcard/taskcard.md" in desc
    assert "manual" in desc.lower()


def test_start_writes_body_before_active_and_reports_exact_paths(agent, manager, monkeypatch):
    renderer = _write_renderer(agent._working_dir, _OK_BODY)
    order: list[str] = []
    real_write_body = manager._write_body
    real_write_status = manager._write_status

    def record_body(body: str) -> None:
        order.append("body")
        real_write_body(body)

    def record_status(value: str) -> None:
        order.append(f"status:{value}")
        real_write_status(value)

    monkeypatch.setattr(manager, "_write_body", record_body)
    monkeypatch.setattr(manager, "_write_status", record_status)

    result = manager.handle(
        {
            "action": "start",
            "input": {"renderer_path": renderer, "interval_s": 3600},
            "reasoning": "publish a task card",
        }
    )

    assert result["status"] == "ok"
    assert result["state"] == "watching"
    assert result["status_value"] == "active"
    assert order == ["body", "status:active"]
    assert Path(result["status_path"]).read_text(encoding="utf-8") == "active"
    assert Path(result["body_path"]).read_text(encoding="utf-8") == "# Task Card\n\n- first\n- second\n"
    manager.handle({"action": "stop", "input": {"watch_id": result["watch_id"]}, "reasoning": "cleanup"})


def test_retry_replaces_only_the_body_and_preserves_active_status(agent, manager, monkeypatch):
    renderer = _write_renderer(agent._working_dir, _OK_BODY)
    started = manager.handle(
        {
            "action": "start",
            "input": {"renderer_path": renderer, "interval_s": 3600},
            "reasoning": "publish a task card",
        }
    )
    Path(renderer).write_text("print('# Updated\\n\\n- replacement')", encoding="utf-8")
    writes: list[str] = []
    real_write_body = manager._write_body
    real_write_status = manager._write_status

    def record_body(body: str) -> None:
        writes.append("body")
        real_write_body(body)

    def record_status(value: str) -> None:
        writes.append(f"status:{value}")
        real_write_status(value)

    monkeypatch.setattr(manager, "_write_body", record_body)
    monkeypatch.setattr(manager, "_write_status", record_status)

    result = manager.handle(
        {
            "action": "retry",
            "input": {"watch_id": started["watch_id"]},
            "reasoning": "refresh now",
        }
    )

    assert result["status"] == "ok"
    assert result["last_valid_body"] == "# Updated\n\n- replacement\n"
    assert Path(result["status_path"]).read_text(encoding="utf-8") == "active"
    assert Path(result["body_path"]).read_text(encoding="utf-8") == "# Updated\n\n- replacement\n"
    assert writes == ["body"]
    manager.handle({"action": "stop", "input": {"watch_id": started["watch_id"]}, "reasoning": "cleanup"})


def test_stop_writes_inactive_before_removing_the_watch(agent, manager, monkeypatch):
    started = manager.handle(
        {
            "action": "start",
            "input": {"renderer_path": _write_renderer(agent._working_dir, _OK_BODY), "interval_s": 3600},
            "reasoning": "publish a task card",
        }
    )
    writes: list[str] = []
    real_write_status = manager._write_status

    def record_status(value: str) -> None:
        writes.append(value)
        real_write_status(value)

    monkeypatch.setattr(manager, "_write_status", record_status)
    result = manager.handle(
        {
            "action": "stop",
            "input": {"watch_id": started["watch_id"]},
            "reasoning": "deactivate",
        }
    )

    assert result["status"] == "ok"
    assert result["state"] == "stopped"
    assert result["status_value"] == "inactive"
    assert Path(result["status_path"]).read_text(encoding="utf-8") == "inactive"
    assert writes == ["inactive"]


def test_only_one_watch_may_be_active_per_agent(agent, manager):
    renderer = _write_renderer(agent._working_dir, _OK_BODY)
    started = manager.handle(
        {
            "action": "start",
            "input": {"renderer_path": renderer, "interval_s": 3600},
            "reasoning": "first watch",
        }
    )
    blocked = manager.handle(
        {
            "action": "start",
            "input": {"renderer_path": renderer, "interval_s": 3600},
            "reasoning": "second watch",
        }
    )

    assert started["status"] == "ok"
    assert blocked["status"] == "failed"
    assert "only one Task Card watch" in blocked["message"]
    manager.handle({"action": "stop", "input": {"watch_id": started["watch_id"]}, "reasoning": "cleanup"})


def test_start_rejects_renderer_path_outside_workdir(agent, manager):
    result = manager.handle(
        {
            "action": "start",
            "input": {"renderer_path": "../../etc/passwd"},
            "reasoning": "probe path escape",
        }
    )
    assert result["status"] == "failed"
    assert "working directory" in result["message"]


@pytest.mark.parametrize(
    "body,kwargs",
    [
        ("pass", {}),
        ("import sys; sys.exit(3)", {}),
        ("import time; time.sleep(5)", {"timeout_s": 0.2}),
    ],
)
def test_start_failures_create_no_watch(agent, manager, body, kwargs):
    result = manager.handle(
        {
            "action": "start",
            "input": {
                "renderer_path": _write_renderer(agent._working_dir, body, "bad.py"),
                **kwargs,
            },
            "reasoning": "probe failure",
        }
    )
    assert result["status"] == "failed"
    assert manager._watch is None


def test_renderer_failure_preserves_last_valid_body_and_emits_error_then_recovery(agent, manager):
    renderer = Path(_write_renderer(agent._working_dir, _OK_BODY))
    started = manager.handle(
        {
            "action": "start",
            "input": {"renderer_path": str(renderer), "interval_s": 3600},
            "reasoning": "publish a task card",
        }
    )
    watch = manager._watch
    assert watch is not None

    renderer.write_text("import sys; sys.exit(1)", encoding="utf-8")
    manager._tick(watch)
    inspected = manager.handle(
        {
            "action": "inspect",
            "input": {"watch_id": started["watch_id"]},
            "reasoning": "inspect failure",
        }
    )
    assert inspected["state"] == "error"
    assert inspected["last_valid_body"] == "# Task Card\n\n- first\n- second\n"
    assert any(wake["source"] == "task_card.error" for wake in agent.wakes)

    renderer.write_text("print('# Recovered')", encoding="utf-8")
    manager._tick(watch)
    assert any(wake["source"] == "task_card.error" and wake["extra"]["state"] == "recovered" for wake in agent.wakes)
    manager.handle({"action": "stop", "input": {"watch_id": started["watch_id"]}, "reasoning": "cleanup"})

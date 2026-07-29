"""Focused Telegram/Task Card LTP-v2 family and refresh-fuse invariants."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lingtai.mcp_servers.telegram._family import (
    TELEGRAM_ACTIONS,
    TELEGRAM_SCHEMA,
    _basic_validate,
    handle_telegram,
)
from lingtai.mcp_servers.telegram.service import TelegramService
from lingtai.mcp_servers.telegram.task_card.controller import TaskCardController

from .test_task_card_controller import _FakeAgent, _OK_BODY, _write_renderer


class _CountingManager:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def handle(self, args: dict) -> dict:
        self.calls.append(dict(args))
        return {"status": "ok", "action": args.get("action")}


def _branches(schema: dict) -> dict[str, dict]:
    inputs = schema["properties"]["input"]
    branches = inputs.get("oneOf") or inputs.get("anyOf")
    return {branch["title"].removesuffix(" input"): branch for branch in branches}


def test_family_dispatch_rejects_root_and_cross_branch_before_manager_io():
    manager = _CountingManager()
    valid = {
        "action": "accounts",
        "input": {},
        "reasoning": "schema probe",
    }
    invalid = [
        {"action": "accounts", "input": {}, "reasoning": "x", "_reasoning": "legacy"},
        {"action": "accounts", "input": {}, "reasoning": "x", "unknown": 1},
        {"action": "accounts", "input": {}, "reasoning": 7},
        {"action": "accounts", "input": {"chat_id": 2}, "reasoning": "x"},
        {"action": "send", "input": {"message_id": "acct:1:2", "text": "x"}, "reasoning": "x"},
        {"action": "send", "input": {"text": "missing chat"}, "reasoning": "x"},
        {"action": "send", "input": {"chat_id": 2, "text": 17}, "reasoning": "x"},
    ]
    for args in invalid:
        result = handle_telegram(manager, args)
        assert result["status"] == "failed", args
        assert manager.calls == []
    assert handle_telegram(manager, valid)["status"] == "ok"
    assert len(manager.calls) == 1


def test_telegram_send_schema_preserves_text_media_chat_action_alternatives():
    send = _branches(TELEGRAM_SCHEMA)["send"]
    assert send["anyOf"] == [
        {"required": ["text"]},
        {"required": ["media"]},
        {"required": ["chat_action"]},
    ]
    assert _basic_validate({"chat_id": 3, "text": "hello"}, send)
    assert _basic_validate({"chat_id": 3, "media": {"type": "photo", "path": "x"}}, send)
    assert _basic_validate({"chat_id": 3, "chat_action": "typing"}, send)
    assert not _basic_validate({"chat_id": 3}, send)
    assert not _basic_validate({"text": "missing chat"}, send)
    assert not _basic_validate({"chat_id": 3, "text": 17}, send)


def test_taskcard_refresh_setting_defaults_invalid_values_preserves_valid_siblings(
    tmp_path, caplog
):
    path = tmp_path / "telegram" / "taskcard.json"
    path.parent.mkdir()
    cases = [
        {},
        {"taskcard": False, "normal_rows": 4, "max_refreshes": True},
        {"taskcard": False, "normal_rows": 4, "max_refreshes": 0},
        {"taskcard": False, "normal_rows": 4, "max_refreshes": "10"},
        {"taskcard": False, "normal_rows": 4, "max_refreshes": 1001},
    ]
    for payload in cases:
        caplog.clear()
        path.write_text(json.dumps(payload))
        service = TelegramService(tmp_path, [{"alias": "acct", "bot_token": "x"}], lambda *_: None)
        assert any("max_refreshes" in record.message for record in caplog.records)
        assert service.taskcard_enabled() is payload.get("taskcard", True)
        assert service.taskcard_normal_rows() == payload.get("normal_rows", 1)
        assert service.taskcard_max_refreshes() == 1000
        service.set_taskcard_max_refreshes(7)
        persisted = json.loads(path.read_text())
        assert persisted["max_refreshes"] == 7
        assert persisted["taskcard"] == service.taskcard_enabled()
        assert persisted["normal_rows"] == service.taskcard_normal_rows()


def test_taskcard_refresh_setting_positive_value_round_trips(tmp_path):
    path = tmp_path / "telegram" / "taskcard.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"taskcard": False, "normal_rows": 3, "max_refreshes": 9}))
    service = TelegramService(tmp_path, [{"alias": "acct", "bot_token": "x"}], lambda *_: None)
    assert service.taskcard_max_refreshes() == 9
    service.set_taskcard_max_refreshes(4)
    assert json.loads(path.read_text())["max_refreshes"] == 4
    with pytest.raises(ValueError, match="1 through 1000"):
        service.set_taskcard_max_refreshes(1001)
    assert json.loads(path.read_text())["max_refreshes"] == 4


def _start_with_ceiling(agent: _FakeAgent, ceiling: int, *, requested=None):
    controller = TaskCardController(agent, max_refreshes_getter=lambda: ceiling)
    args = {
        "action": "start",
        "renderer_path": _write_renderer(agent._working_dir, _OK_BODY),
        "interval_s": 3600,
    }
    if requested is not None:
        args["max_refreshes"] = requested
    return controller, controller.handle(args)


def test_controller_defensively_caps_malformed_host_ceiling_at_1000(tmp_path):
    agent = _FakeAgent(tmp_path)
    controller, start = _start_with_ceiling(agent, 1001)
    assert start["max_refreshes"] == 1000
    controller.handle({"action": "stop", "watch_id": start["watch_id"]})


@pytest.mark.parametrize("mode", ["success", "renderer_failure", "backend_failure"])
def test_refresh_count_ceiling_counts_later_attempts_and_emits_safe_limit_once(
    mode, tmp_path
):
    agent = _FakeAgent(tmp_path)
    controller, start = _start_with_ceiling(agent, 2)
    assert start["refreshes_used"] == 0
    assert start["max_refreshes"] == 2
    assert start["refreshes_remaining"] == 2
    watch = controller._watches[start["watch_id"]]
    renderer = Path(watch.renderer_path)
    if mode == "renderer_failure":
        renderer.write_text("import sys; sys.exit(1)")
    elif mode == "backend_failure":
        agent._client.fail = True

    # The initial create is excluded; two later attempts consume exactly two
    # permits regardless of renderer/backend success or failure.
    controller._tick(watch)
    controller._tick(watch)
    inspected = controller._inspect(watch)
    assert inspected["refreshes_used"] == 2
    assert inspected["max_refreshes"] == 2
    assert inspected["refreshes_remaining"] == 0
    assert inspected["stop_reason"] == "max_refreshes"
    assert inspected["state"] in {"stopped", "stop_failed"}

    limit_wakes = [w for w in agent.wakes if w["source"] == "task_card.limit"]
    assert len(limit_wakes) == 1
    wake = limit_wakes[0]
    assert wake["priority"] == "normal"
    assert wake["skip_if_idempotency_key_exists"] is True
    assert wake["idempotency_key"] == "task_card.limit:tc_1:2"
    assert wake["extra"] == {
        "watch_id": "tc_1",
        "state": "stopped",
        "reason": "max_refreshes",
        "used": 2,
        "max": 2,
        "last_valid_frame_at": inspected["last_valid_frame_at"],
    }
    assert "renderer" not in wake["body"].lower()
    assert str(renderer) not in wake["body"]
    assert all(secret not in wake["body"] for secret in ("acct", "42"))

    # A third attempt cannot begin and does not produce another backend call or
    # limit wake, even when the stop/finalize path retained a retryable handle.
    calls = len(agent._client.calls)
    controller._tick(watch)
    assert len(agent._client.calls) == calls
    assert len([w for w in agent.wakes if w["source"] == "task_card.limit"]) == 1


@pytest.mark.parametrize("mode", ["renderer_failure", "backend_failure"])
def test_terminal_failed_refresh_emits_only_limit_notification(mode, tmp_path):
    agent = _FakeAgent(tmp_path)
    controller, start = _start_with_ceiling(agent, 1)
    watch = controller._watches[start["watch_id"]]
    if mode == "renderer_failure":
        Path(watch.renderer_path).write_text("import sys; sys.exit(1)")
    else:
        agent._client.fail = True

    controller._tick(watch)

    assert [wake["source"] for wake in agent.wakes] == ["task_card.limit"]
    assert agent.wakes[0]["extra"]["reason"] == "max_refreshes"


def test_start_ceiling_is_global_hard_cap_and_requested_value_only_lowers(tmp_path):
    agent = _FakeAgent(tmp_path)
    controller, start = _start_with_ceiling(agent, 3, requested=99)
    assert start["max_refreshes"] == 3
    controller.handle({"action": "stop", "watch_id": start["watch_id"]})
    for requested in (0, -1, True, "2"):
        fresh = _FakeAgent(tmp_path)
        ctrl = TaskCardController(fresh, max_refreshes_getter=lambda: 3)
        args = {"action": "start", "renderer_path": _write_renderer(tmp_path, _OK_BODY)}
        args["max_refreshes"] = requested
        result = ctrl.handle(args)
        assert result["status"] == "error"
        assert fresh._client.calls == []


def test_limit_finalize_failure_retains_retryable_stop_state_without_restart(tmp_path):
    agent = _FakeAgent(tmp_path)
    controller, start = _start_with_ceiling(agent, 1)
    watch = controller._watches[start["watch_id"]]
    agent._client.fail = True
    controller._tick(watch)
    failed = controller._inspect(watch)
    assert failed["state"] == "stop_failed"
    assert failed["stop_reason"] == "max_refreshes"
    assert failed["error"]["code"] == "stop_finalize_failed"
    assert watch.stop_event.is_set()
    assert start["watch_id"] in controller._watches
    assert len([w for w in agent.wakes if w["source"] == "task_card.limit"]) == 1

    # Recovery retries only finalize: no new renderer/update is allowed and the
    # retained handle is removed once the safe clear is accepted.
    calls = len(agent._client.calls)
    agent._client.fail = False
    result = controller.handle({"action": "retry", "watch_id": start["watch_id"]})
    assert result["state"] == "stopped"
    assert start["watch_id"] not in controller._watches
    assert len(agent._client.calls) == calls + 1
    assert agent._client.calls[-1][1]["sub_action"] == "finalize"


def test_openai_responses_scrub_preserves_family_root_and_action_branches():
    from lingtai.llm.openai.adapter import _scrub_responses_schema

    wire = _scrub_responses_schema(copy.deepcopy(TELEGRAM_SCHEMA), is_root=True)
    assert wire["required"] == TELEGRAM_SCHEMA["required"]
    assert wire["properties"]["action"]["enum"] == list(TELEGRAM_ACTIONS)
    assert wire["properties"]["input"]["anyOf"]
    assert len(wire["allOf"]) == len(TELEGRAM_ACTIONS)
    assert wire["additionalProperties"] is False

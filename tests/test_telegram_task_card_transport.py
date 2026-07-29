"""Regression tests for the real MCP transport boundary of the private Task
Card tool.

The card is projected by a *private MCP tool name* that ``list_tools`` never
returns. Official SDK v2's low-level ``Server`` validates the typed request
envelope but not the advertised per-tool ``input_schema``, so for per-tool
argument semantics the server's own handler is the only gate: the unlisted
private name is forced onto the task-card action, and the public ``telegram``
name is refused that action explicitly. Everything else is rejected by
``TelegramManager`` itself. These tests drive a real in-memory ``Client``
against the real ``build_server`` so the genuine dispatch path runs in-process.
"""

from __future__ import annotations

import json
from pathlib import Path

import anyio
import mcp.types as types
import pytest
from mcp import Client
from mcp.shared.exceptions import MCPError

from lingtai.kernel.base_agent import _TASK_CARD_TOOL
from lingtai.mcp_servers.telegram.manager import TelegramManager
from lingtai.mcp_servers.telegram.server import _PRIVATE_TASK_CARD_TOOL, build_server
from tests._notification_store_helpers import FakeNotificationStore


def test_private_task_card_tool_name_literals_are_in_sync():
    """The private tool name is duplicated on purpose: the kernel must not import
    ``mcp_servers``, so ``kernel.base_agent._TASK_CARD_TOOL`` mirrors the server's
    ``_PRIVATE_TASK_CARD_TOOL`` as a literal. Both source comments say "keep the
    two in sync"; this pins that invariant so a drift in either literal — which
    would silently break the reverse channel — fails a test instead."""
    assert _TASK_CARD_TOOL == _PRIVATE_TASK_CARD_TOOL


class _FakeAccount:
    alias = "mybot"

    def __init__(self):
        self.calls: list = []

    def send_message(self, chat_id, text, reply_to_message_id=None, **kwargs):
        msg_id = len(self.calls) + 100
        self.calls.append(("send_message", chat_id, text, reply_to_message_id, kwargs))
        return {"message_id": msg_id}

    def edit_message(self, chat_id, message_id, text, **kwargs):
        self.calls.append(("edit_message", chat_id, message_id, text))
        return {"ok": True}


class _FakeService:
    def __init__(self):
        self.default_account = _FakeAccount()

    def get_account(self, alias):
        assert alias == "mybot"
        return self.default_account


def _make_manager(tmp_path):
    service = _FakeService()
    manager = TelegramManager(
        service,
        working_dir=Path(tmp_path),
        on_inbound=lambda _: None,
        notification_store=FakeNotificationStore(),
    )
    return manager, service.default_account


def _call_tool_via_transport(manager, name, arguments):
    """Drive a real ``tools/call`` through an in-memory v2 client."""
    async def _run():
        async with Client(build_server(manager)) as client:
            return await client.call_tool(name, arguments)

    return anyio.run(_run)


def _list_tools_via_transport(manager):
    async def _run():
        async with Client(build_server(manager)) as client:
            return (await client.list_tools()).tools

    return anyio.run(_run)


def _flatten_exception(exc):
    """Yield ``exc`` and, for an ExceptionGroup, every exception it carries."""
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _flatten_exception(inner)
    else:
        yield exc


def _payload(result):
    assert result.content, "expected at least one content block"
    block = result.content[0]
    assert isinstance(block, types.TextContent)
    return json.loads(block.text)


def test_private_tool_name_reaches_manager_and_creates_card(tmp_path):
    """The unlisted private tool name passes the transport (no validation) and
    creates a card. The caller sends NO ``action``; the server forces it."""
    manager, account = _make_manager(tmp_path)

    result = _call_tool_via_transport(manager, _PRIVATE_TASK_CARD_TOOL, {
        "sub_action": "create",
        "account": "mybot",
        "chat_id": 999,
        "tool": "bash",
        "tool_action": "run",
        "reasoning": "Check project structure",
    })

    assert result.is_error is False
    payload = _payload(result)
    assert payload["status"] == "ok"
    assert "message_id" in payload

    send_calls = [c for c in account.calls if c[0] == "send_message"]
    assert len(send_calls) == 1
    assert "📋 TASK CARD" in send_calls[0][2]


def test_list_tools_exposes_exact_public_families_in_order(tmp_path):
    """Raw MCP exposes exactly Telegram then Task Card; reverse route is hidden."""
    manager, _ = _make_manager(tmp_path)
    names = [t.name for t in _list_tools_via_transport(manager)]
    assert names == ["telegram", "task_card"]
    assert _PRIVATE_TASK_CARD_TOOL not in names


def test_public_telegram_with_private_action_rejected_by_handler(tmp_path):
    """Even if the private action is guessed, the public ``telegram`` name
    refuses it.

    SDK v2 never applies the advertised schema, so the public ``SCHEMA`` enum
    is no longer what blocks this; the handler rejects the private action on
    the public name explicitly. This is the isolation the hidden route depends
    on, so it is asserted at the transport, not at the manager.
    """
    manager, account = _make_manager(tmp_path)

    result = _call_tool_via_transport(manager, "telegram", {
        "action": "_task_card_update",
        "sub_action": "create",
        "account": "mybot",
        "chat_id": 999,
    })

    assert result.is_error is True
    assert not any(c[0] == "send_message" for c in account.calls)


def test_private_tool_cannot_be_repurposed_for_public_actions(tmp_path):
    """A public ``action`` smuggled through the private tool is overwritten by
    the server, so the hidden route only ever dispatches the task-card action."""
    manager, account = _make_manager(tmp_path)

    result = _call_tool_via_transport(manager, _PRIVATE_TASK_CARD_TOOL, {
        "action": "send",
        "chat_id": 999,
        "text": "smuggled public send",
        "sub_action": "create",
        "account": "mybot",
        "tool": "bash",
        "reasoning": "x",
    })

    # Forced to _task_card_update: a card is sent, not the smuggled public send.
    payload = _payload(result)
    assert payload["status"] == "ok"
    send_calls = [c for c in account.calls if c[0] == "send_message"]
    assert len(send_calls) == 1
    assert "📋 TASK CARD" in send_calls[0][2]
    assert "smuggled public send" not in send_calls[0][2]


def test_invalid_public_action_rejected(tmp_path):
    """A bogus public action is rejected before any transport side effect.

    Under v2 the rejection comes from ``TelegramManager`` rather than the
    library, but it stays a model-readable ``is_error`` result and still sends
    nothing.
    """
    manager, account = _make_manager(tmp_path)

    result = _call_tool_via_transport(manager, "telegram", {
        "action": "totally_not_a_real_action",
    })

    assert result.is_error is True
    assert not any(c[0] == "send_message" for c in account.calls)


def test_public_action_wrong_type_rejected(tmp_path):
    """A public ``send`` with a wrongly-typed ``chat_id`` is still rejected.

    v2 never applies the advertised per-tool schema, so this is the manager's
    own type/route checking — which is what actually protects the send path —
    and nothing is sent.
    """
    manager, account = _make_manager(tmp_path)

    result = _call_tool_via_transport(manager, "telegram", {
        "action": "send",
        "chat_id": "not-an-integer",
        "text": "hi",
    })

    assert result.is_error is True
    assert not any(c[0] == "send_message" for c in account.calls)


def test_unknown_tool_name_rejected(tmp_path):
    """Any other unlisted tool name remains rejected by the handler.

    A lookup miss is an ``InvalidParamsError`` under the 2026-07-28 schema, so
    the rejection is an ``MCPError`` carrying ``-32602`` and the requested
    name. Either way the name never reaches the manager and nothing is sent.
    """
    manager, account = _make_manager(tmp_path)

    # The in-memory dispatcher surfaces the failure through a task group, so
    # the MCPError arrives inside an ExceptionGroup.
    with pytest.raises(BaseException) as raised:
        _call_tool_via_transport(manager, "not_a_real_tool", {"action": "send"})

    errors = [
        exc for exc in _flatten_exception(raised.value) if isinstance(exc, MCPError)
    ]
    assert errors, f"expected an MCPError, got {raised.value!r}"
    assert errors[0].code == types.INVALID_PARAMS
    assert errors[0].message == "Unknown tool: not_a_real_tool"
    assert errors[0].data == {"requested": "not_a_real_tool"}
    assert not any(c[0] == "send_message" for c in account.calls)


def test_each_public_family_has_strict_root_and_action_owned_branches(tmp_path):
    manager, _ = _make_manager(tmp_path)
    tools = _list_tools_via_transport(manager)
    assert [tool.name for tool in tools] == ["telegram", "task_card"]
    for tool in tools:
        schema = tool.input_schema
        assert schema["required"] == ["action", "input", "reasoning"]
        assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
        assert schema["additionalProperties"] is False
        assert len(schema["allOf"]) == len(schema["properties"]["action"]["enum"])
        branches = schema["properties"]["input"].get(
            "oneOf", schema["properties"]["input"].get("anyOf")
        )
        assert len(branches) == len(schema["properties"]["action"]["enum"])


def test_raw_task_card_manual_is_family_owned_and_flat_root_is_rejected(tmp_path):
    manager, account = _make_manager(tmp_path)
    manual = _call_tool_via_transport(
        manager,
        "task_card",
        {"action": "manual", "input": {}, "reasoning": "discover lifecycle"},
    )
    assert manual.is_error is False
    assert _payload(manual)["action"] == "manual"
    assert not account.calls

    # Missing strict envelope fields is rejected by the listed schema before any
    # host-bound controller or manager operation.
    flat = _call_tool_via_transport(manager, "task_card", {"action": "manual"})
    assert flat.is_error is True
    assert not account.calls


def test_raw_task_card_cross_branch_input_is_rejected_before_controller_io(tmp_path):
    manager, account = _make_manager(tmp_path)
    result = _call_tool_via_transport(
        manager,
        "task_card",
        {
            "action": "inspect",
            "input": {"renderer_path": "watch.py"},
            "reasoning": "cross branch probe",
        },
    )
    assert result.is_error is True
    assert not account.calls

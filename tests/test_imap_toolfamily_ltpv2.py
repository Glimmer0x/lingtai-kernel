"""Focused IMAP LTP-v2 family invariants (mirrors telegram's toolfamily test)."""
from __future__ import annotations

import copy

from lingtai.mcp_servers.imap._family import (
    IMAP_ACTIONS,
    IMAP_SCHEMA,
    _basic_validate,
    handle_imap,
)


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
        {"action": "accounts", "input": {"email_id": "a:b:1"}, "reasoning": "x"},
        {"action": "send", "input": {"note": "wrong branch key"}, "reasoning": "x"},
        {"action": "send", "input": {}, "reasoning": "x"},
        {"action": "move", "input": {"email_id": "a:b:1"}, "reasoning": "x"},
        {"action": "flag", "input": {"email_id": "a:b:1"}, "reasoning": "x"},
        {"action": "add_contact", "input": {"address": "a@b.com"}, "reasoning": "x"},
    ]
    for args in invalid:
        result = handle_imap(manager, args)
        assert result["status"] == "failed", args
        assert manager.calls == []
    assert handle_imap(manager, valid)["status"] == "ok"
    assert len(manager.calls) == 1
    assert manager.calls[0] == {"action": "accounts"}


def test_family_dispatch_forwards_flat_input_to_manager_handle():
    manager = _CountingManager()
    handle_imap(manager, {
        "action": "send",
        "input": {"address": "a@b.com", "message": "hi"},
        "reasoning": "x",
    })
    handle_imap(manager, {
        "action": "move",
        "input": {"email_id": "a:b:1", "folder": "Archive"},
        "reasoning": "x",
    })
    handle_imap(manager, {
        "action": "flag",
        "input": {"email_id": "a:b:1", "flags": {"seen": True}},
        "reasoning": "x",
    })
    assert manager.calls == [
        {"action": "send", "address": "a@b.com", "message": "hi"},
        {"action": "move", "email_id": "a:b:1", "folder": "Archive"},
        {"action": "flag", "email_id": "a:b:1", "flags": {"seen": True}},
    ]


def test_manual_action_bypasses_manager_when_manager_is_none():
    result = handle_imap(None, {"action": "manual", "input": {}, "reasoning": "x"})
    assert result["status"] == "ok"
    assert result["skill"] == "imap-mcp-manual"
    assert isinstance(result["manual"], str) and result["manual"].strip()


def test_imap_actions_match_exact_public_inventory():
    assert IMAP_ACTIONS == (
        "send", "check", "read", "reply", "search",
        "delete", "move", "flag", "folders",
        "contacts", "add_contact", "remove_contact", "edit_contact",
        "accounts", "settings", "manual",
    )
    assert list(IMAP_SCHEMA["properties"]["action"]["enum"]) == list(IMAP_ACTIONS)


def test_imap_send_schema_requires_address_and_rejects_unknown_fields():
    send = _branches(IMAP_SCHEMA)["send"]
    assert send["required"] == ["address"]
    assert _basic_validate({"address": "a@b.com", "message": "hi"}, send)
    assert not _basic_validate({"message": "missing address"}, send)
    assert not _basic_validate({"address": "a@b.com", "bogus": 1}, send)


def test_imap_move_schema_requires_email_id_and_destination_folder():
    move = _branches(IMAP_SCHEMA)["move"]
    assert set(move["required"]) == {"email_id", "folder"}
    assert _basic_validate({"email_id": "a:b:1", "folder": "Archive"}, move)
    assert not _basic_validate({"email_id": "a:b:1"}, move)


def test_imap_flag_schema_requires_email_id_and_flags():
    flag = _branches(IMAP_SCHEMA)["flag"]
    assert set(flag["required"]) == {"email_id", "flags"}
    assert _basic_validate({"email_id": "a:b:1", "flags": {"seen": True}}, flag)
    assert not _basic_validate({"email_id": "a:b:1"}, flag)


def test_imap_root_envelope_is_strict_ltp_v2():
    assert IMAP_SCHEMA["required"] == ["action", "input", "reasoning"]
    assert IMAP_SCHEMA["additionalProperties"] is False
    assert "reasoning" in IMAP_SCHEMA["properties"]
    assert "summarize" in IMAP_SCHEMA["properties"]
    assert len(IMAP_SCHEMA["allOf"]) == len(IMAP_ACTIONS)


def test_openai_responses_scrub_preserves_family_root_and_action_branches():
    from lingtai.llm.openai.adapter import _scrub_responses_schema

    wire = _scrub_responses_schema(copy.deepcopy(IMAP_SCHEMA), is_root=True)
    assert wire["required"] == IMAP_SCHEMA["required"]
    assert wire["properties"]["action"]["enum"] == list(IMAP_ACTIONS)
    assert wire["properties"]["input"]["anyOf"]
    assert len(wire["allOf"]) == len(IMAP_ACTIONS)
    assert wire["additionalProperties"] is False

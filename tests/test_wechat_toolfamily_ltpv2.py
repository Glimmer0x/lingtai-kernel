"""Focused WeChat LTP-v2 family strict-schema and dispatch-routing tests.

Mirrors ``tests/test_telegram_toolfamily_ltpv2.py``: proves the composed root
schema shape (``action``/``input``/``reasoning``/``summarize``), the
``allOf``/``if``/``then`` action<->input correlation, and that
``handle_wechat``/``WechatManager.handle`` reject malformed envelopes,
cross-action field leakage, missing required root fields, and unknown
actions/params (``ACTION_REQUIRED`` / ``INVALID_ARGUMENT``) before any
manager I/O — then that every one of the 10 real actions routes to the
correct flat manager call. ``send``'s ``text``/``media_path`` is a
non-exclusive ``anyOf`` (the manager sends both in one call when both are
given), not a ``oneOf`` choice — covered explicitly below.
"""
from __future__ import annotations

import copy

import pytest

from lingtai.mcp_servers.wechat._family import (
    WECHAT_ACTIONS,
    WECHAT_SCHEMA,
    _basic_validate,
    handle_wechat,
)
from lingtai.mcp_servers.wechat.manager import WechatManager


class _CountingManager:
    """A minimal manager double that records every flat call it receives."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def handle(self, args: dict) -> dict:
        self.calls.append(dict(args))
        return {"status": "ok", "action": args.get("action")}


def _branches(schema: dict) -> dict[str, dict]:
    inputs = schema["properties"]["input"]
    branches = inputs.get("oneOf") or inputs.get("anyOf")
    return {branch["title"].removesuffix(" input"): branch for branch in branches}


# ---------------------------------------------------------------------------
# Root envelope shape
# ---------------------------------------------------------------------------

def test_root_schema_has_exactly_the_ltp_v2_envelope_fields():
    props = WECHAT_SCHEMA["properties"]
    assert set(props) == {"action", "input", "reasoning", "summarize"}
    assert WECHAT_SCHEMA["required"] == ["action", "input", "reasoning"]
    assert WECHAT_SCHEMA["additionalProperties"] is False
    assert props["action"]["enum"] == list(WECHAT_ACTIONS)
    assert props["reasoning"]["type"] == "string"
    assert props["summarize"]["type"] == "boolean"


def test_action_enum_is_exactly_the_ten_wechat_actions():
    assert WECHAT_ACTIONS == (
        "send", "check", "read", "reply", "search",
        "contacts", "add_contact", "remove_contact", "accounts", "manual",
    )


def test_root_allof_correlates_every_action_with_its_own_input_branch():
    all_of = WECHAT_SCHEMA["allOf"]
    assert len(all_of) == len(WECHAT_ACTIONS)
    branches = _branches(WECHAT_SCHEMA)
    seen_actions = set()
    for condition in all_of:
        action = condition["if"]["properties"]["action"]["const"]
        assert condition["if"]["required"] == ["action"]
        assert action in WECHAT_ACTIONS
        seen_actions.add(action)
        # then.input must be exactly that action's own canonical branch,
        # modulo the branch-only "title" key the oneOf disclosure adds.
        then_input = dict(condition["then"]["properties"]["input"])
        own_branch = dict(branches[action])
        own_branch.pop("title", None)
        assert then_input == own_branch
    assert seen_actions == set(WECHAT_ACTIONS)


def test_no_audit_or_presentation_field_leaks_into_any_action_branch():
    for action in WECHAT_ACTIONS:
        branch = _branches(WECHAT_SCHEMA)[action]
        props = branch.get("properties", {})
        assert "reasoning" not in props
        assert "_reasoning" not in props
        assert "summarize" not in props
        assert "action" not in props


# ---------------------------------------------------------------------------
# Strict-schema accept/reject per action (via the dependency-free validator
# the dispatch boundary itself uses)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("action", "valid_input"),
    [
        ("send", {"user_id": "wxid_a@im.wechat", "text": "hi"}),
        ("send", {"user_id": "wxid_a@im.wechat", "media_path": "/tmp/x.png"}),
        ("send", {"user_id": "wxid_a@im.wechat", "text": "hi", "media_path": "/tmp/x.png"}),
        ("check", {}),
        ("read", {"user_id": "wxid_a@im.wechat"}),
        ("read", {"user_id": "wxid_a@im.wechat", "limit": 5}),
        ("reply", {"message_id": "abc", "text": "hi"}),
        ("search", {"query": "hello"}),
        ("search", {"query": "hello", "user_id": "wxid_a@im.wechat"}),
        ("contacts", {}),
        ("add_contact", {"user_id": "wxid_a@im.wechat", "alias": "friend"}),
        ("remove_contact", {"alias": "friend"}),
        ("remove_contact", {"user_id": "wxid_a@im.wechat"}),
        ("accounts", {}),
        ("manual", {}),
    ],
)
def test_valid_payload_accepted_per_action(action, valid_input):
    schema = _branches(WECHAT_SCHEMA)[action]
    assert _basic_validate(valid_input, schema)


@pytest.mark.parametrize(
    ("action", "bad_input"),
    [
        # missing required fields
        ("send", {"text": "no user_id"}),
        ("send", {"user_id": "wxid_a@im.wechat"}),  # neither text nor media_path
        ("read", {}),  # user_id required
        ("reply", {"message_id": "abc"}),  # text required
        ("reply", {"text": "hi"}),  # message_id required
        ("search", {}),  # query required
        ("add_contact", {"user_id": "wxid_a@im.wechat"}),  # alias required
        ("remove_contact", {}),  # neither alias nor user_id
        # cross-action field leakage
        ("send", {"user_id": "a", "text": "hi", "message_id": "reply-only"}),
        ("reply", {"message_id": "abc", "text": "hi", "user_id": "leak"}),
        ("search", {"query": "x", "media_path": "leak"}),
        ("check", {"user_id": "leak"}),
        ("contacts", {"query": "leak"}),
        ("accounts", {"alias": "leak"}),
        ("manual", {"reasoning": "leak"}),
        # wrong types
        ("send", {"user_id": "a", "text": 5}),
        ("read", {"user_id": "a", "limit": "not-an-int"}),
        ("add_contact", {"user_id": 5, "alias": "friend"}),
    ],
)
def test_invalid_payload_rejected_per_action(action, bad_input):
    schema = _branches(WECHAT_SCHEMA)[action]
    assert not _basic_validate(bad_input, schema)


# ---------------------------------------------------------------------------
# handle_wechat: envelope-level rejection before any manager I/O
# ---------------------------------------------------------------------------

def test_family_dispatch_rejects_root_and_cross_branch_before_manager_io():
    manager = _CountingManager()
    valid = {"action": "accounts", "input": {}, "reasoning": "schema probe"}
    invalid = [
        # legacy out-of-band reasoning key must not be tolerated
        {"action": "accounts", "input": {}, "reasoning": "x", "_reasoning": "legacy"},
        # unknown root field
        {"action": "accounts", "input": {}, "reasoning": "x", "unknown": 1},
        # reasoning wrong type / missing
        {"action": "accounts", "input": {}, "reasoning": 7},
        {"action": "accounts", "input": {}},
        # summarize wrong type
        {"action": "accounts", "input": {}, "reasoning": "x", "summarize": "yes"},
        # missing root fields entirely
        {"input": {}, "reasoning": "x"},
        {"action": "send", "reasoning": "x"},
        {"action": "send", "input": {"user_id": "a", "text": "hi"}},
        # cross-action field leakage caught at dispatch too, not just schema
        ("accounts", {"user_id": "leak"}),
        # unknown action
        {"action": "not_a_real_action", "input": {}, "reasoning": "x"},
        {"action": "delete", "input": {}, "reasoning": "x"},  # telegram-only action
        # unhashable action (issue #513 class) must not raise
        {"action": [], "input": {}, "reasoning": "x"},
        {"action": {}, "input": {}, "reasoning": "x"},
    ]
    for case in invalid:
        if isinstance(case, tuple):
            action, bad_input = case
            args = {"action": action, "input": bad_input, "reasoning": "x"}
        else:
            args = case
        result = handle_wechat(manager, args)
        assert result["status"] == "failed", args
        assert result["error_code"] in {"ACTION_REQUIRED", "INVALID_ARGUMENT"}, args
        assert manager.calls == [], args

    assert handle_wechat(manager, valid)["status"] == "ok"
    assert len(manager.calls) == 1


def test_unhashable_action_returns_action_required_not_typeerror():
    manager = _CountingManager()
    for bad_action in ([], {}, {"nested": 1}):
        result = handle_wechat(manager, {"action": bad_action, "input": {}, "reasoning": "x"})
        assert result == {
            "status": "failed",
            "error_code": "ACTION_REQUIRED",
            "message": "invalid wechat action",
        }
    assert manager.calls == []


def test_unsupported_root_argument_is_rejected_before_action_lookup():
    manager = _CountingManager()
    result = handle_wechat(
        manager,
        {"action": "accounts", "input": {}, "reasoning": "x", "extra_root_key": 1},
    )
    assert result == {
        "status": "failed",
        "error_code": "INVALID_ARGUMENT",
        "message": "unsupported wechat argument",
    }
    assert manager.calls == []


# ---------------------------------------------------------------------------
# Dispatch routing: every one of the 10 actions reaches the correct flat
# manager call with only its own validated input.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("action", "action_input"),
    [
        ("send", {"user_id": "wxid_a@im.wechat", "text": "hi"}),
        ("check", {}),
        ("read", {"user_id": "wxid_a@im.wechat", "limit": 3}),
        ("reply", {"message_id": "abc", "text": "hi"}),
        ("search", {"query": "hello"}),
        ("contacts", {}),
        ("add_contact", {"user_id": "wxid_a@im.wechat", "alias": "friend"}),
        ("remove_contact", {"alias": "friend"}),
        ("accounts", {}),
        ("manual", {}),
    ],
)
def test_dispatch_routes_each_action_to_flat_manager_call(action, action_input):
    manager = _CountingManager()
    args = {"action": action, "input": action_input, "reasoning": "probe"}
    result = handle_wechat(manager, args)

    assert result == {"status": "ok", "action": action}
    assert len(manager.calls) == 1
    # The child handler must receive exactly {"action": action, **input} —
    # never "reasoning", "_reasoning", or "summarize".
    assert manager.calls[0] == {"action": action, **action_input}


# ---------------------------------------------------------------------------
# B1 regression: send's text/media_path is a non-exclusive combination
# (the manager sends both in one call — text chunks then the media message),
# not a oneOf choice. anyOf must accept text-only, media-only, and both
# together; it must still reject neither, and cross-branch/host keys must
# still be rejected before any manager I/O.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "send_input",
    [
        {"user_id": "wxid_a@im.wechat", "text": "hi"},
        {"user_id": "wxid_a@im.wechat", "media_path": "/tmp/x.png"},
        {"user_id": "wxid_a@im.wechat", "text": "hi", "media_path": "/tmp/x.png"},
    ],
)
def test_send_accepts_text_only_media_only_and_text_plus_media(send_input):
    schema = _branches(WECHAT_SCHEMA)["send"]
    assert _basic_validate(send_input, schema)

    manager = _CountingManager()
    result = handle_wechat(
        manager, {"action": "send", "input": send_input, "reasoning": "probe"},
    )
    assert result == {"status": "ok", "action": "send"}
    assert manager.calls == [{"action": "send", **send_input}]


@pytest.mark.parametrize(
    "bad_send_input",
    [
        {"user_id": "wxid_a@im.wechat"},  # neither text nor media_path
        {"user_id": "wxid_a@im.wechat", "text": "hi", "message_id": "reply-only"},  # cross-branch
        {"user_id": "wxid_a@im.wechat", "text": "hi", "host_agent_id": "x"},  # host-only key
        {"text": "hi", "media_path": "/tmp/x.png"},  # missing required user_id
    ],
)
def test_send_still_rejects_neither_field_and_cross_branch_host_keys(bad_send_input):
    schema = _branches(WECHAT_SCHEMA)["send"]
    assert not _basic_validate(bad_send_input, schema)

    manager = _CountingManager()
    result = handle_wechat(
        manager, {"action": "send", "input": bad_send_input, "reasoning": "probe"},
    )
    assert result["status"] == "failed"
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert manager.calls == []


def test_dispatch_covers_all_ten_actions_exactly_once():
    manager = _CountingManager()
    inputs = {
        "send": {"user_id": "a", "text": "hi"},
        "check": {},
        "read": {"user_id": "a"},
        "reply": {"message_id": "m", "text": "hi"},
        "search": {"query": "q"},
        "contacts": {},
        "add_contact": {"user_id": "a", "alias": "x"},
        "remove_contact": {"alias": "x"},
        "accounts": {},
        "manual": {},
    }
    assert set(inputs) == set(WECHAT_ACTIONS)
    for action in WECHAT_ACTIONS:
        handle_wechat(manager, {"action": action, "input": inputs[action], "reasoning": "r"})
    assert [c["action"] for c in manager.calls] == list(WECHAT_ACTIONS)


# ---------------------------------------------------------------------------
# Real WechatManager: envelope routing + manual/no-double-wrap + error parity
# ---------------------------------------------------------------------------

def _manager(tmp_path):
    return WechatManager(
        token="test-token",
        user_id="test-bot",
        working_dir=tmp_path,
        on_inbound=lambda event: None,
    )


def test_real_manager_handle_detects_envelope_shape_and_routes_through_family(tmp_path):
    mgr = _manager(tmp_path)
    result = mgr.handle({"action": "accounts", "input": {}, "reasoning": "probe"})
    assert result["status"] == "ok"
    assert result["accounts"] == ["default"]


def test_real_manager_rejects_cross_branch_field_before_send_io(tmp_path, monkeypatch):
    mgr = _manager(tmp_path)
    called = {"n": 0}
    monkeypatch.setattr(mgr, "_handle_send", lambda args: called.__setitem__("n", 1) or {})

    result = mgr.handle({
        "action": "send",
        "input": {"user_id": "a", "text": "hi", "message_id": "reply-only-field"},
        "reasoning": "x",
    })

    assert result["status"] == "failed"
    assert result["error_code"] == "INVALID_ARGUMENT"
    assert called["n"] == 0


def test_real_manager_manual_action_matches_flat_manual_contract(tmp_path):
    mgr = _manager(tmp_path)
    enveloped = mgr.handle({"action": "manual", "input": {}, "reasoning": "probe"})
    flat = mgr.handle({"action": "manual"})

    # No double-wrap: the family-routed result is byte-identical to the
    # manager's own pre-migration flat manual result.
    assert enveloped == flat
    assert enveloped["status"] == "ok"
    assert enveloped["skill"] == "wechat-mcp-manual"
    assert set(enveloped) == {"status", "action", "skill", "metadata", "path", "manual"}


def test_real_manager_unknown_action_via_envelope_is_action_required(tmp_path):
    mgr = _manager(tmp_path)
    result = mgr.handle({"action": "delete", "input": {}, "reasoning": "x"})
    assert result == {
        "status": "failed",
        "error_code": "ACTION_REQUIRED",
        "message": "invalid wechat action",
    }


def test_real_manager_flat_internal_shape_still_used_for_re_entry(tmp_path):
    """The manager's own re-entry path (child handler -> manager.handle with a
    flat {"action": ..., **input} mapping) must still work — it is not the
    public envelope, and must not require input/reasoning."""
    mgr = _manager(tmp_path)
    result = mgr.handle({"action": "accounts"})
    assert result["status"] == "ok"
    assert result["accounts"] == ["default"]


# ---------------------------------------------------------------------------
# Wire-parity: composed schema survives a JSON round trip and remains a valid
# plain-dict JSON Schema shape (no non-serializable objects).
# ---------------------------------------------------------------------------

def test_schema_round_trips_through_json_unchanged():
    import json

    dumped = json.dumps(WECHAT_SCHEMA)
    reloaded = json.loads(dumped)
    assert reloaded == WECHAT_SCHEMA


def test_schema_is_deep_copy_safe_between_calls():
    from lingtai.mcp_servers.wechat._family import wechat_schema

    first = wechat_schema()
    second = wechat_schema()
    assert first == second
    assert first is not second
    first["properties"]["action"]["enum"].append("mutated")
    assert "mutated" not in second["properties"]["action"]["enum"]


def test_openai_responses_scrub_preserves_family_root_and_action_branches():
    from lingtai.llm.openai.adapter import _scrub_responses_schema

    wire = _scrub_responses_schema(copy.deepcopy(WECHAT_SCHEMA), is_root=True)
    assert wire["required"] == WECHAT_SCHEMA["required"]
    assert wire["properties"]["action"]["enum"] == list(WECHAT_ACTIONS)
    assert wire["properties"]["input"]["anyOf"] or wire["properties"]["input"]["oneOf"]
    assert len(wire["allOf"]) == len(WECHAT_ACTIONS)
    assert wire["additionalProperties"] is False

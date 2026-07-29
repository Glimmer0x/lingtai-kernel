"""Focused Cloud Mail LTP-v2 family tests: strict envelope, dispatch boundary."""
from __future__ import annotations

import copy
import re

from lingtai.mcp_servers.cloud_mail import manager as cloud_mail_mgr
from lingtai.mcp_servers.cloud_mail._family import (
    CLOUD_MAIL_ACTIONS,
    CLOUD_MAIL_SCHEMA,
    _basic_validate,
    _cloud_mail_input_schemas,
    handle_cloud_mail,
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


def test_schema_declares_strict_root_envelope():
    assert set(CLOUD_MAIL_SCHEMA["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert CLOUD_MAIL_SCHEMA["required"] == ["action", "input", "reasoning"]
    assert CLOUD_MAIL_SCHEMA["additionalProperties"] is False
    assert CLOUD_MAIL_SCHEMA["properties"]["action"]["enum"] == list(CLOUD_MAIL_ACTIONS)
    assert set(_branches(CLOUD_MAIL_SCHEMA)) == set(CLOUD_MAIL_ACTIONS)


def test_family_dispatch_rejects_root_and_cross_branch_before_manager_io():
    manager = _CountingManager()
    valid = {"action": "accounts", "input": {}, "reasoning": "schema probe"}
    invalid = [
        # legacy compatibility field must not be forwarded/accepted
        {"action": "accounts", "input": {}, "reasoning": "x", "_reasoning": "legacy"},
        {"action": "accounts", "input": {}, "reasoning": "x", "unknown": 1},
        {"action": "accounts", "input": {}, "reasoning": 7},
        # cross-branch: 'address' belongs to send, not accounts
        {"action": "accounts", "input": {"address": "x@y.com"}, "reasoning": "x"},
        # send requires 'address'
        {"action": "send", "input": {"message": "missing address"}, "reasoning": "x"},
        # unknown action
        {"action": "bogus", "input": {}, "reasoning": "x"},
        # missing input
        {"action": "check", "reasoning": "x"},
        # missing reasoning
        {"action": "check", "input": {}},
        # summarize wrong type
        {"action": "check", "input": {}, "reasoning": "x", "summarize": "yes"},
    ]
    for args in invalid:
        result = handle_cloud_mail(manager, args)
        assert result["status"] == "failed", args
        assert manager.calls == []
    ok = handle_cloud_mail(manager, valid)
    assert ok["status"] == "ok"
    assert len(manager.calls) == 1
    assert manager.calls[0] == {"action": "accounts"}


def test_send_requires_address_and_accepts_valid_input():
    manager = _CountingManager()
    result = handle_cloud_mail(
        manager,
        {
            "action": "send",
            "input": {"address": ["a@x.com", "b@x.com"], "message": "hi"},
            "reasoning": "send test",
        },
    )
    assert result["status"] == "ok"
    assert manager.calls[-1] == {
        "action": "send", "address": ["a@x.com", "b@x.com"], "message": "hi",
    }
    assert not _basic_validate({}, _branches(CLOUD_MAIL_SCHEMA)["send"])
    assert _basic_validate({"address": "x@y.com"}, _branches(CLOUD_MAIL_SCHEMA)["send"])


def test_reasoning_and_summarize_never_reach_manager_input():
    manager = _CountingManager()
    handle_cloud_mail(
        manager,
        {
            "action": "check",
            "input": {"limit": 5},
            "reasoning": "why",
            "summarize": True,
        },
    )
    assert manager.calls == [{"action": "check", "limit": 5}]


def test_manual_action_dispatches_to_manager_manual():
    manager = _CountingManager()
    result = handle_cloud_mail(manager, {"action": "manual", "input": {}, "reasoning": "x"})
    assert result["status"] == "ok"
    assert manager.calls == [{"action": "manual"}]


def test_manual_action_without_manager_returns_bundled_skill():
    result = handle_cloud_mail(None, {"action": "manual", "input": {}, "reasoning": "x"})
    assert result["status"] == "ok"
    assert result["action"] == "manual"
    assert result["skill"] == "cloud-mail-mcp-manual"
    assert isinstance(result["manual"], str) and result["manual"].strip()


def test_openai_responses_scrub_preserves_family_root_and_action_branches():
    from lingtai.llm.openai.adapter import _scrub_responses_schema

    wire = _scrub_responses_schema(copy.deepcopy(CLOUD_MAIL_SCHEMA), is_root=True)
    assert wire["required"] == CLOUD_MAIL_SCHEMA["required"]
    assert wire["properties"]["action"]["enum"] == list(CLOUD_MAIL_ACTIONS)
    assert wire["properties"]["input"]["anyOf"]
    assert wire["additionalProperties"] is False


# ---------------------------------------------------------------------------
# Manual (SKILL.md) truthfulness — guards against re-drifting to a flat/legacy
# example or an undocumented root ``summarize`` control (CONTRACT.md
# "Dispatch and actions" MUST).
# ---------------------------------------------------------------------------

def test_manual_documents_the_ltp_v2_envelope_and_summarize_profile():
    body = cloud_mail_mgr._SKILL_BODY
    lowered = body.lower()
    assert "action, input, reasoning" in lowered or "action`, `input`, and\n`reasoning`" in body
    assert "summarize" in lowered
    assert "bulky-result" in lowered
    assert "short-result" in lowered


def test_manual_never_teaches_the_retired_check_n_alias():
    # 'n' was a flat-shape alias for 'limit' on the pre-migration manager
    # dispatch; the LTP-v2 'check' input branch does not accept it
    # (additionalProperties: false), so the manual must not teach it.
    assert "check" in _cloud_mail_input_schemas()
    assert "n" not in _cloud_mail_input_schemas()["check"]["properties"]
    body = cloud_mail_mgr._SKILL_BODY
    assert not re.search(r"`limit`/`n`", body)
    assert not re.search(r"optional[^.\n]*\bn\b[^.\n]*filters", body, re.IGNORECASE)

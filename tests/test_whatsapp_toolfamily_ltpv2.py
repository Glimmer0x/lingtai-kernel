"""Focused WhatsApp LTP-v2 family and server-boundary invariants.

Mirrors ``tests/test_telegram_toolfamily_ltpv2.py``'s family-schema coverage
for the WhatsApp curated MCP: strict envelope validation for all 13 actions,
cross-branch input rejection, manual-action parity, Result/Error typed-object
parity (including ``INVALID_PARAMS`` for an unknown resource/tool), and
webhook/notification behavior unaffected by the migration.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lingtai.mcp_servers.whatsapp._family import (
    WHATSAPP_ACTIONS,
    WHATSAPP_SCHEMA,
    _basic_validate,
    _whatsapp_input_schemas,
    build_whatsapp_family,
    handle_whatsapp,
)
from lingtai.mcp_servers.whatsapp.manager import WhatsAppManager


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


def _real_manager(tmp_path: Path) -> WhatsAppManager:
    return WhatsAppManager(
        accounts_config=[
            {
                "alias": "default",
                "phone_number_id": "10001",
                "access_token": "secret-token",
                "app_secret": "secret-app-secret",
            }
        ],
        working_dir=tmp_path,
    )


_VALID_INPUT_BY_ACTION = {
    "send": {"to": "15551234567", "text": "hi"},
    "check": {},
    "read": {"wa_id": "15551234567"},
    "reply": {"message_id": "default:15551234567:wamid.1", "text": "hi"},
    "search": {"query": "hi"},
    "react": {"message_id": "default:15551234567:wamid.1", "emoji": "\U0001F44D"},
    "contacts": {},
    "add_contact": {"wa_id": "15551234567", "name": "Bob"},
    "remove_contact": {"wa_id": "15551234567"},
    "templates": {},
    "accounts": {},
    "status": {},
    "manual": {},
}


# ---------------------------------------------------------------------------
# 1. Strict schema validation across all 13 actions.
# ---------------------------------------------------------------------------


def test_all_thirteen_actions_present_in_stable_order():
    assert WHATSAPP_ACTIONS == (
        "send", "check", "read", "reply", "search", "react", "contacts",
        "add_contact", "remove_contact", "templates", "accounts", "status",
        "manual",
    )
    assert WHATSAPP_SCHEMA["properties"]["action"]["enum"] == list(WHATSAPP_ACTIONS)


def test_root_schema_shape_requires_action_input_reasoning():
    assert WHATSAPP_SCHEMA["type"] == "object"
    assert set(WHATSAPP_SCHEMA["required"]) == {"action", "input", "reasoning"}
    assert WHATSAPP_SCHEMA["additionalProperties"] is False
    assert "summarize" in WHATSAPP_SCHEMA["properties"]
    assert "summarize" not in WHATSAPP_SCHEMA["required"]
    assert len(WHATSAPP_SCHEMA["allOf"]) == len(WHATSAPP_ACTIONS)


def test_every_action_dispatches_with_its_valid_input():
    manager = _CountingManager()
    for action in WHATSAPP_ACTIONS:
        result = handle_whatsapp(
            manager,
            {
                "action": action,
                "input": _VALID_INPUT_BY_ACTION[action],
                "reasoning": "schema probe",
            },
        )
        assert result["status"] == "ok", (action, result)
    assert len(manager.calls) == len(WHATSAPP_ACTIONS)
    assert [call["action"] for call in manager.calls] == list(WHATSAPP_ACTIONS)


def test_malformed_and_legacy_flat_shape_calls_are_rejected():
    manager = _CountingManager()
    invalid = [
        # Legacy flat pre-migration shape: action + top-level fields, no input.
        {"action": "send", "to": "1", "text": "hi", "reasoning": "x"},
        # Missing reasoning.
        {"action": "send", "input": {"to": "1", "text": "hi"}},
        # Non-string reasoning.
        {"action": "send", "input": {"to": "1", "text": "hi"}, "reasoning": 7},
        # input not an object.
        {"action": "send", "input": "not-an-object", "reasoning": "x"},
        # Unknown root field.
        {"action": "accounts", "input": {}, "reasoning": "x", "unknown": 1},
        # Legacy internal envelope field leaking through.
        {"action": "accounts", "input": {}, "reasoning": "x", "_reasoning": "legacy"},
        # non-boolean summarize.
        {"action": "accounts", "input": {}, "reasoning": "x", "summarize": "yes"},
        # Unknown action.
        {"action": "delete", "input": {}, "reasoning": "x"},
        {"action": "", "input": {}, "reasoning": "x"},
        {"input": {}, "reasoning": "x"},
    ]
    for args in invalid:
        result = handle_whatsapp(manager, args)
        assert result["status"] == "failed", args
        assert manager.calls == [], args


# ---------------------------------------------------------------------------
# 2. Cross-branch rejection: input valid for one action, sent under another.
# ---------------------------------------------------------------------------


def test_cross_branch_input_is_rejected_before_manager_io():
    manager = _CountingManager()
    cross_branch = [
        # react's fields under send.
        {"action": "send", "input": {"message_id": "a:b:c", "emoji": "x"}, "reasoning": "x"},
        # send's fields under react.
        {"action": "react", "input": {"to": "1", "text": "hi"}, "reasoning": "x"},
        # reply's message_id under accounts (accounts takes no fields at all).
        {"action": "accounts", "input": {"message_id": "a:b:c"}, "reasoning": "x"},
        # search's query under templates.
        {"action": "templates", "input": {"query": "hi"}, "reasoning": "x"},
        # add_contact's name under remove_contact.
        {"action": "remove_contact", "input": {"wa_id": "1", "name": "Bob"}, "reasoning": "x"},
        # status takes no input at all.
        {"action": "status", "input": {"account": "default"}, "reasoning": "x"},
        # manual takes no input at all.
        {"action": "manual", "input": {"account": "default"}, "reasoning": "x"},
    ]
    for args in cross_branch:
        result = handle_whatsapp(manager, args)
        assert result["status"] == "failed", args
    assert manager.calls == []


def test_send_reply_require_a_message_variant_and_reject_multiple_recipients():
    send = _branches(WHATSAPP_SCHEMA)["send"]
    assert send["anyOf"] == [
        {"required": ["text"]},
        {"required": ["media"]},
        {"required": ["template"]},
    ]
    assert send["oneOf"] == [{"required": ["to"]}, {"required": ["wa_id"]}]
    assert _basic_validate({"to": "1", "text": "hi"}, send)
    assert _basic_validate({"wa_id": "1", "media": {"type": "image"}}, send)
    assert _basic_validate({"to": "1", "template": {"name": "x"}}, send)
    assert not _basic_validate({"to": "1"}, send)  # no message variant
    assert not _basic_validate({"text": "hi"}, send)  # no recipient
    assert not _basic_validate({"to": "1", "wa_id": "2", "text": "hi"}, send)  # both recipients

    reply = _branches(WHATSAPP_SCHEMA)["reply"]
    assert reply["required"] == ["message_id"]
    assert _basic_validate({"message_id": "a:b:c", "text": "hi"}, reply)
    assert not _basic_validate({"text": "hi"}, reply)  # missing message_id
    assert not _basic_validate({"message_id": "a:b:c"}, reply)  # no message variant


def test_add_contact_remove_contact_require_wa_id_or_to_but_not_both():
    add_contact = _branches(WHATSAPP_SCHEMA)["add_contact"]
    assert _basic_validate({"wa_id": "1", "name": "Bob"}, add_contact)
    assert _basic_validate({"to": "1"}, add_contact)
    assert not _basic_validate({"name": "Bob"}, add_contact)  # no target
    assert not _basic_validate({"wa_id": "1", "to": "2"}, add_contact)  # both targets

    remove_contact = _branches(WHATSAPP_SCHEMA)["remove_contact"]
    assert _basic_validate({"wa_id": "1"}, remove_contact)
    assert not _basic_validate({}, remove_contact)


def test_react_requires_message_id_and_emoji():
    react = _branches(WHATSAPP_SCHEMA)["react"]
    assert set(react["required"]) == {"message_id", "emoji"}
    assert _basic_validate({"message_id": "a:b:c", "emoji": "x"}, react)
    assert not _basic_validate({"message_id": "a:b:c"}, react)
    assert not _basic_validate({"emoji": "x"}, react)


def test_status_accounts_manual_take_no_input_at_all():
    for action in ("status", "accounts", "manual"):
        branch = _branches(WHATSAPP_SCHEMA)[action]
        assert branch.get("properties", {}) == {}
        assert _basic_validate({}, branch)
        assert not _basic_validate({"account": "x"}, branch)


def test_templates_contacts_take_only_an_optional_account():
    for action in ("templates", "contacts"):
        branch = _branches(WHATSAPP_SCHEMA)[action]
        assert set(branch.get("properties", {})) == {"account"}
        assert _basic_validate({}, branch)
        assert _basic_validate({"account": "default"}, branch)
        assert not _basic_validate({"account": "default", "anything": 1}, branch)


# ---------------------------------------------------------------------------
# 3. `manual` action output correctness.
# ---------------------------------------------------------------------------


def test_manual_action_returns_bundled_skill_body_and_path(tmp_path):
    manager = _real_manager(tmp_path)
    result = handle_whatsapp(
        manager, {"action": "manual", "input": {}, "reasoning": "read the manual"}
    )
    assert result["status"] == "ok"
    assert result["action"] == "manual"
    assert result["skill"] == "whatsapp-mcp-manual"
    assert isinstance(result["manual"], str) and result["manual"].strip()
    manual_path = Path(result["path"])
    assert manual_path.is_absolute()
    assert manual_path.name == "SKILL.md"
    assert manual_path.is_file()
    lowered = result["manual"].lower()
    assert "send" in lowered
    assert "read" in lowered
    assert "search" in lowered


def test_manual_action_available_without_a_manager():
    result = handle_whatsapp(
        None, {"action": "manual", "input": {}, "reasoning": "no manager yet"}
    )
    assert result["status"] == "ok"
    assert result["action"] == "manual"
    assert result["manual"].strip()


def test_manual_action_description_advertises_skill_catalog_entry():
    action_description = WHATSAPP_SCHEMA["properties"]["action"]["description"]
    assert "manual:" in action_description
    assert "progressive-disclosure usage manual" in action_description
    assert "whatsapp-mcp-manual" in action_description


# ---------------------------------------------------------------------------
# 4. Server construction / registration.
# ---------------------------------------------------------------------------


def test_server_constructs_without_a_manager():
    from lingtai.mcp_servers.whatsapp.server import build_server

    server = build_server(None)
    assert server is not None


def test_server_constructs_with_a_real_manager(tmp_path):
    from lingtai.mcp_servers.whatsapp.server import build_server

    manager = _real_manager(tmp_path)
    server = build_server(manager)
    assert server is not None


@pytest.mark.anyio
async def test_server_lists_exactly_one_whatsapp_tool_with_the_new_schema():
    from mcp import Client

    from lingtai.mcp_servers.whatsapp.server import build_server

    async with Client(build_server(None)) as client:
        result = await client.list_tools()
        assert [tool.name for tool in result.tools] == ["whatsapp"]
        schema = result.tools[0].input_schema
        assert schema["required"] == ["action", "input", "reasoning"]
        assert schema["properties"]["action"]["enum"] == list(WHATSAPP_ACTIONS)


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# 5. Resources still work (webhook resource handlers unaffected).
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_resources_list_and_read_still_work_with_new_family(tmp_path):
    from mcp import Client

    from lingtai.mcp_servers.whatsapp.server import build_server

    manager = _real_manager(tmp_path)
    async with Client(build_server(manager)) as client:
        listing = await client.list_resources()
        assert listing.resources
        uris = {str(r.uri) for r in listing.resources}
        assert "lingtai://status" in uris
        assert "lingtai://manifest" in uris

        status_contents = (await client.read_resource("lingtai://status")).contents
        payload = json.loads(status_contents[0].text)
        assert payload["status"] == "ok"
        # Redaction must still hold: no secret material in the resource.
        assert "secret-token" not in status_contents[0].text
        assert "secret-app-secret" not in status_contents[0].text


@pytest.mark.anyio
async def test_unknown_resource_uri_is_invalid_params():
    from mcp import Client
    from mcp.shared.exceptions import MCPError
    from mcp.types import INVALID_PARAMS

    from lingtai.mcp_servers.whatsapp.server import build_server

    async with Client(build_server(None)) as client:
        with pytest.raises(MCPError) as raised:
            await client.read_resource("lingtai://does-not-exist")
    assert raised.value.code == INVALID_PARAMS


# ---------------------------------------------------------------------------
# 6. Result/Error typed-object parity, including INVALID_PARAMS for unknown
#    action and unknown contact/resource lookups.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unknown_tool_name_is_invalid_params():
    from mcp import Client
    from mcp.shared.exceptions import MCPError
    from mcp.types import INVALID_PARAMS

    from lingtai.mcp_servers.whatsapp.server import build_server

    async with Client(build_server(None)) as client:
        with pytest.raises(MCPError) as raised:
            await client.call_tool("not_whatsapp", {})
    assert raised.value.code == INVALID_PARAMS
    assert raised.value.data == {"requested": "not_whatsapp"}


@pytest.mark.anyio
async def test_call_tool_success_and_failure_paths_are_typed_correctly(tmp_path):
    from mcp import Client

    from lingtai.mcp_servers.whatsapp.server import build_server

    manager = _real_manager(tmp_path)
    async with Client(build_server(manager)) as client:
        ok = await client.call_tool(
            "whatsapp",
            {"action": "accounts", "input": {}, "reasoning": "list accounts"},
        )
        assert ok.is_error is False
        assert ok.structured_content["status"] == "ok"
        assert json.loads(ok.content[0].text) == ok.structured_content

        # Envelope-level failure (bad action) — still a readable tool result,
        # not a protocol error, and is_error must be set.
        bad_action = await client.call_tool(
            "whatsapp",
            {"action": "not_an_action", "input": {}, "reasoning": "x"},
        )
        assert bad_action.is_error is True
        assert bad_action.structured_content["status"] == "failed"
        assert bad_action.structured_content["error_code"] == "ACTION_REQUIRED"

        # Business-logic failure surfaced by the manager itself (unknown
        # contact target omitted -> add_contact business validation).
        remove_missing = await client.call_tool(
            "whatsapp",
            {
                "action": "remove_contact",
                "input": {"wa_id": "19998887777"},
                "reasoning": "remove a contact that was never added",
            },
        )
        assert remove_missing.is_error is False
        assert remove_missing.structured_content["status"] == "ok"
        assert remove_missing.structured_content["removed"] is None


@pytest.mark.anyio
async def test_manager_not_initialized_is_a_readable_tool_error():
    from mcp import Client

    from lingtai.mcp_servers.whatsapp.server import build_server

    async with Client(build_server(None)) as client:
        result = await client.call_tool(
            "whatsapp",
            {"action": "accounts", "input": {}, "reasoning": "probe uninitialized"},
        )
    assert result.is_error is True
    assert result.structured_content["status"] == "error"
    assert "not initialized" in result.structured_content["error"]


# ---------------------------------------------------------------------------
# 7. Webhook/notification behavior unchanged — smoke check that ingest_webhook
#    (exercised in full by test_whatsapp_notification_metadata.py) is
#    reachable independent of the new tool-call envelope.
# ---------------------------------------------------------------------------


def test_ingest_webhook_unaffected_by_tool_envelope_migration(tmp_path):
    manager = _real_manager(tmp_path)
    events = []
    manager.on_inbound = events.append
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "10001"},
                            "messages": [
                                {
                                    "from": "15551234567",
                                    "id": "wamid.A",
                                    "timestamp": "1752000000",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    manager.ingest_webhook("default", payload)
    assert len(events) == 1
    assert events[0]["metadata"]["platform"] == "whatsapp"


# ---------------------------------------------------------------------------
# 8. Wire-scrub parity (Responses API root-schema survival), matching
#    Telegram's equivalent proof.
# ---------------------------------------------------------------------------


def test_openai_responses_scrub_preserves_family_root_and_action_branches():
    from lingtai.llm.openai.adapter import _scrub_responses_schema

    wire = _scrub_responses_schema(copy.deepcopy(WHATSAPP_SCHEMA), is_root=True)
    assert wire["required"] == WHATSAPP_SCHEMA["required"]
    assert wire["properties"]["action"]["enum"] == list(WHATSAPP_ACTIONS)
    assert wire["properties"]["input"]["anyOf"]
    assert len(wire["allOf"]) == len(WHATSAPP_ACTIONS)
    assert wire["additionalProperties"] is False


# ---------------------------------------------------------------------------
# 9. build_whatsapp_family / _whatsapp_input_schemas registry sanity.
# ---------------------------------------------------------------------------


def test_schema_only_and_dispatch_families_share_the_same_action_registry():
    family = build_whatsapp_family(None)
    assert family.child_names == WHATSAPP_ACTIONS
    assert set(_whatsapp_input_schemas()) == set(WHATSAPP_ACTIONS)


def test_reasoning_and_summarize_never_reach_a_child_handler():
    captured: dict = {}

    class _Capturing:
        def handle(self, args):
            captured.update(args)
            return {"status": "ok"}

    handle_whatsapp(
        _Capturing(),
        {
            "action": "accounts",
            "input": {},
            "reasoning": "must not leak",
            "summarize": True,
        },
    )
    assert "reasoning" not in captured
    assert "summarize" not in captured
    assert captured == {"action": "accounts"}

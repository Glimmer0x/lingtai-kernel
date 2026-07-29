"""IMAP's independent LTP-v2 tool family.

This module owns only the public IMAP envelope and action branches. The
manager remains the legacy result/business boundary behind the validated
family — mirrors ``telegram/_family.py``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lingtai.tools.tool_family import ChildTool, ToolFamily

from .. import _skill

# Kept local to avoid importing the manager (which consumes this schema).
_SKILL_NAME = "imap-mcp-manual"
_SKILL_FRONTMATTER, _SKILL_BODY, _SKILL_PATH = _skill.load_skill(
    "lingtai.mcp_servers.imap"
)

_ACTIONS = (
    "send", "check", "read", "reply", "search",
    "delete", "move", "flag", "folders",
    "contacts", "add_contact", "remove_contact", "edit_contact",
    "accounts", "manual",
)


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {"anyOf": [schema, {"type": "null"}]}


def _object(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    return result


def _address_list() -> dict[str, Any]:
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}},
        ],
    }


def _email_id_list() -> dict[str, Any]:
    return {
        "anyOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}},
        ],
        "description": "Email ID(s) — compound key: account:folder:uid",
    }


def _account_field() -> dict[str, Any]:
    return _nullable({
        "type": "string",
        "description": (
            "Which account to use (email address). Optional — an empty or "
            "whitespace-only string is treated as omitted and defaults to "
            "the primary account."
        ),
    })


def _imap_input_schemas() -> dict[str, dict[str, Any]]:
    send = _object(
        {
            "account": _account_field(),
            "address": _address_list(),
            "subject": {"type": "string", "description": "Email subject line"},
            "message": {"type": "string", "description": "Email body"},
            "cc": _address_list(),
            "bcc": _address_list(),
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of file paths to attach (absolute or relative to "
                    "working dir)."
                ),
            },
        },
        required=["address"],
    )
    send["properties"]["address"]["description"] = "Target email address(es) for send"
    send["properties"]["cc"]["description"] = "CC address(es)"
    send["properties"]["bcc"]["description"] = "BCC address(es)"

    check = _object({
        "account": _account_field(),
        "folder": _nullable({
            "type": "string",
            "description": (
                "IMAP folder name (e.g. INBOX, [Gmail]/Sent Mail). An empty "
                "or whitespace-only string is treated as omitted and "
                "defaults to INBOX."
            ),
        }),
        "n": _nullable({
            "type": "integer",
            "description": "Max recent emails to show (default 10)",
        }),
    })

    read = _object(
        {
            "account": _account_field(),
            "email_id": _email_id_list(),
        },
        required=["email_id"],
    )

    reply = _object(
        {
            "account": _account_field(),
            "email_id": _email_id_list(),
            "subject": {"type": "string", "description": "Email subject line"},
            "message": {"type": "string", "description": "Email body"},
            "cc": _address_list(),
            "attachments": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "List of file paths to attach (absolute or relative to "
                    "working dir)."
                ),
            },
        },
        required=["email_id", "message"],
    )
    reply["properties"]["cc"]["description"] = "CC address(es)"

    search = _object(
        {
            "account": _account_field(),
            "query": {
                "type": "string",
                "description": (
                    "IMAP search query (e.g. from:addr subject:text unseen "
                    "since:YYYY-MM-DD)"
                ),
            },
            "folder": _nullable({
                "type": "string",
                "description": (
                    "IMAP folder name. An empty or whitespace-only string is "
                    "treated as omitted and defaults to INBOX."
                ),
            }),
        },
        required=["query"],
    )

    delete = _object(
        {
            "account": _account_field(),
            "email_id": _email_id_list(),
        },
        required=["email_id"],
    )

    move = _object(
        {
            "account": _account_field(),
            "email_id": _email_id_list(),
            "folder": {
                "type": "string",
                "description": (
                    "Destination folder for move. Must be a non-empty name — "
                    "never defaulted to INBOX."
                ),
            },
        },
        required=["email_id", "folder"],
    )

    flag = _object(
        {
            "account": _account_field(),
            "email_id": _email_id_list(),
            "flags": {
                "type": "object",
                "description": (
                    "Required — dict of flag name to bool, e.g. "
                    "{\"seen\": true, \"flagged\": false}"
                ),
            },
        },
        required=["email_id", "flags"],
    )

    folders = _object({"account": _account_field()})
    contacts = _object({"account": _account_field()})

    add_contact = _object(
        {
            "account": _account_field(),
            "address": {"type": "string", "description": "Contact's email address"},
            "name": {
                "type": "string",
                "description": "Contact's human-readable name",
            },
            "note": {"type": "string", "description": "Free-text note about the contact"},
        },
        required=["address", "name"],
    )

    remove_contact = _object(
        {
            "account": _account_field(),
            "address": {"type": "string", "description": "Contact's email address"},
        },
        required=["address"],
    )

    edit_contact = _object(
        {
            "account": _account_field(),
            "address": {"type": "string", "description": "Contact's email address"},
            "name": {
                "type": "string",
                "description": "Contact's human-readable name",
            },
            "note": {"type": "string", "description": "Free-text note about the contact"},
        },
        required=["address"],
    )

    accounts = _object({})
    empty = _object({})
    return {
        "send": send,
        "check": check,
        "read": read,
        "reply": reply,
        "search": search,
        "delete": delete,
        "move": move,
        "flag": flag,
        "folders": folders,
        "contacts": contacts,
        "add_contact": add_contact,
        "remove_contact": remove_contact,
        "edit_contact": edit_contact,
        "accounts": accounts,
        "manual": empty,
    }


def _schema_only_family() -> ToolFamily:
    schemas = _imap_input_schemas()
    return ToolFamily(
        "imap",
        [
            ChildTool(action, schemas[action], lambda _input: {})
            for action in _ACTIONS
        ],
    )


_SCHEMA_FAMILY = _schema_only_family()


def imap_schema() -> dict[str, Any]:
    schema = _SCHEMA_FAMILY.build_schema()
    # IMAP has intentionally overlapping optional fields (for example every
    # action accepts optional account). The root allOf discriminator still
    # correlates each action to its exact closed branch; use anyOf for the
    # model-discovery list so native JSON-Schema validators do not reject a
    # valid input merely because another action's branch also fits.
    schema["properties"]["input"]["anyOf"] = schema["properties"]["input"].pop("oneOf")
    schema["properties"]["action"]["description"] = (
        "send: send email via IMAP/SMTP (requires address, message; optional "
        "subject, cc, bcc, attachments). "
        "check: list recent envelopes from a folder (optional folder, n). "
        "read: fetch full email by ID list (email_id=[id1, ...]). "
        "You are encouraged to read multiple relevant or even all unread "
        "emails and think before acting. "
        "reply: reply to an email (requires email_id, message; optional cc, "
        "attachments). "
        "search: server-side IMAP search (requires query, optional folder). "
        "delete: delete email(s) by ID (email_id). "
        "move: move email(s) to another folder (email_id, folder=destination). "
        "flag: set/clear flags on email(s) (email_id, flags={flag: bool}, e.g. "
        "flags={'seen': true}). "
        "folders: list available IMAP folders. "
        "contacts: list all contacts. "
        "add_contact: add/update contact (requires address, name; optional "
        "note). "
        "remove_contact: remove contact (requires address). "
        "edit_contact: update contact fields (requires address; optional "
        "name, note). "
        "accounts: list configured IMAP accounts and connection status. "
        + _skill.manual_action_description(_SKILL_FRONTMATTER, _SKILL_NAME)
    )
    return schema


def _basic_validate(value: Any, schema: Mapping[str, Any]) -> bool:
    """Small dependency-free validator for the dispatch safety boundary.

    JSON-Schema combinators compose with sibling constraints. Validate them
    first without returning early, then validate the schema's own type,
    required fields, properties, and bounds.
    """
    if "anyOf" in schema and not any(
        _basic_validate(value, branch) for branch in schema["anyOf"]
    ):
        return False
    if "oneOf" in schema and sum(
        _basic_validate(value, branch) for branch in schema["oneOf"]
    ) != 1:
        return False
    expected = schema.get("type")
    if expected is None:
        required = schema.get("required")
        if required is None:
            return True
        return isinstance(value, Mapping) and all(key in value for key in required)
    if expected == "object":
        if not isinstance(value, Mapping):
            return False
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(properties):
            return False
        if any(key not in value for key in schema.get("required", [])):
            return False
        if not all(
            key not in value or _basic_validate(item, child_schema)
            for key, child_schema in properties.items()
            for item in [value.get(key)]
        ):
            return False
        return True
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str) and value in schema.get("enum", [value])
    if expected == "integer":
        return (
            type(value) is int
            and value in schema.get("enum", [value])
            and value >= schema.get("minimum", value)
            and value <= schema.get("maximum", value)
        )
    if expected == "number":
        return (
            type(value) in (int, float)
            and not isinstance(value, bool)
            and value >= schema.get("minimum", value)
            and value <= schema.get("maximum", value)
        )
    if expected == "boolean":
        return type(value) is bool
    if expected == "null":
        return value is None
    return True


def build_imap_family(manager: Any | None) -> ToolFamily:
    schemas = _imap_input_schemas()
    children: list[ChildTool] = []
    for action in _ACTIONS:
        if action == "manual":
            handler = (
                (lambda _input: manager.handle({"action": "manual"}))
                if manager is not None
                else lambda _input: _skill.manual_payload(
                    _SKILL_FRONTMATTER, _SKILL_BODY, _SKILL_PATH, _SKILL_NAME
                )
            )
        else:
            handler = (
                (lambda input_, action=action: manager.handle({"action": action, **dict(input_)}))
                if manager is not None else (lambda _input: {})
            )
        children.append(ChildTool(action, schemas[action], handler))
    return ToolFamily("imap", children)


def handle_imap(manager: Any | None, args: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(args or {})
    if set(raw) - {"action", "input", "reasoning", "summarize"}:
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "unsupported imap argument"}
    action = raw.get("action")
    if type(action) is not str or action not in _ACTIONS:
        return {"status": "failed", "error_code": "ACTION_REQUIRED", "message": "invalid imap action"}
    if "input" not in raw or not isinstance(raw.get("input"), Mapping):
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "input must be an object"}
    if type(raw.get("reasoning")) is not str:
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "reasoning is required"}
    if "summarize" in raw and type(raw["summarize"]) is not bool:
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "summarize must be a boolean"}
    schema = _imap_input_schemas()[action]
    if not _basic_validate(raw["input"], schema):
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "invalid imap input"}
    return build_imap_family(manager).handle(raw)


IMAP_SCHEMA = imap_schema()
IMAP_ACTIONS = _ACTIONS

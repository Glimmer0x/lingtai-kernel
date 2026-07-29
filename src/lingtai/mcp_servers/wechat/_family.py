"""WeChat's independent LTP-v2 tool family.

This module owns only the public WeChat envelope and action branches. The
manager remains the legacy result/business boundary behind the validated
family, mirroring ``lingtai.mcp_servers.telegram._family``.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lingtai.tools.tool_family import ChildTool, ToolFamily

from .. import _skill

# Kept local to avoid importing the manager (which consumes this schema).
_SKILL_NAME = "wechat-mcp-manual"
_SKILL_FRONTMATTER, _SKILL_BODY, _SKILL_PATH = _skill.load_skill(
    "lingtai.mcp_servers.wechat"
)

_ACTIONS = (
    "send", "check", "read", "reply", "search",
    "contacts", "add_contact", "remove_contact", "accounts", "manual",
)


def _object(
    properties: dict[str, Any],
    *,
    required: list[str] | None = None,
    one_of: list[dict[str, Any]] | None = None,
    any_of: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        result["required"] = required
    if one_of:
        result["oneOf"] = one_of
    if any_of:
        result["anyOf"] = any_of
    return result


def _wechat_input_schemas() -> dict[str, dict[str, Any]]:
    send = _object(
        {
            "user_id": {
                "type": "string",
                "description": "WeChat user ID (e.g. wxid_abc123@im.wechat)",
            },
            "text": {
                "type": "string",
                "description": "Message text content",
            },
            "media_path": {
                "type": "string",
                "description": (
                    "Absolute path to a file to send as media. "
                    "Type detected from extension: "
                    ".jpg/.png=image, .mp4=video, .wav/.mp3=voice, other=file."
                ),
            },
        },
        required=["user_id"],
        any_of=[{"required": ["text"]}, {"required": ["media_path"]}],
    )
    return {
        "send": send,
        "check": _object({}),
        "read": _object(
            {
                "user_id": {
                    "type": "string",
                    "description": "WeChat user ID (e.g. wxid_abc123@im.wechat)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max messages to return (default 10)",
                },
            },
            required=["user_id"],
        ),
        "reply": _object(
            {
                "message_id": {
                    "type": "string",
                    "description": "Message ID from read results (for reply action)",
                },
                "text": {
                    "type": "string",
                    "description": "Message text content",
                },
            },
            required=["message_id", "text"],
        ),
        "search": _object(
            {
                "query": {
                    "type": "string",
                    "description": "Search query (regex pattern)",
                },
                "user_id": {
                    "type": "string",
                    "description": "WeChat user ID (e.g. wxid_abc123@im.wechat)",
                },
            },
            required=["query"],
        ),
        "contacts": _object({}),
        "add_contact": _object(
            {
                "user_id": {
                    "type": "string",
                    "description": "WeChat user ID (e.g. wxid_abc123@im.wechat)",
                },
                "alias": {
                    "type": "string",
                    "description": "Human-friendly contact alias",
                },
            },
            required=["user_id", "alias"],
        ),
        "remove_contact": _object(
            {
                "user_id": {
                    "type": "string",
                    "description": "WeChat user ID (e.g. wxid_abc123@im.wechat)",
                },
                "alias": {
                    "type": "string",
                    "description": "Human-friendly contact alias",
                },
            },
            one_of=[{"required": ["alias"]}, {"required": ["user_id"]}],
        ),
        "accounts": _object({}),
        "manual": _object({}),
    }


def _schema_only_family() -> ToolFamily:
    schemas = _wechat_input_schemas()
    return ToolFamily(
        "wechat",
        [
            ChildTool(action, schemas[action], lambda _input: {})
            for action in _ACTIONS
        ],
    )


_SCHEMA_FAMILY = _schema_only_family()


def wechat_schema() -> dict[str, Any]:
    schema = _SCHEMA_FAMILY.build_schema()
    schema["properties"]["action"]["description"] = (
        "send: send a message to a WeChat user "
        "(user_id, text; optional media_path for file/image/voice/video). "
        "check: list recent conversations with unread counts. "
        "read: read messages from a user (user_id; optional limit). "
        "reply: reply to a specific message "
        "(message_id from read results, text). "
        "search: search inbox messages by regex "
        "(query; optional user_id). "
        "contacts: list saved contacts. "
        "add_contact: save a contact (user_id, alias). "
        "remove_contact: remove a contact (alias or user_id). "
        "accounts: list configured WeChat accounts. "
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


def build_wechat_family(manager: Any | None) -> ToolFamily:
    schemas = _wechat_input_schemas()
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
    return ToolFamily("wechat", children)


def handle_wechat(manager: Any | None, args: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(args or {})
    if set(raw) - {"action", "input", "reasoning", "summarize"}:
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "unsupported wechat argument"}
    action = raw.get("action")
    if type(action) is not str or action not in _ACTIONS:
        return {"status": "failed", "error_code": "ACTION_REQUIRED", "message": "invalid wechat action"}
    if "input" not in raw or not isinstance(raw.get("input"), Mapping):
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "input must be an object"}
    if type(raw.get("reasoning")) is not str:
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "reasoning is required"}
    if "summarize" in raw and type(raw["summarize"]) is not bool:
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "summarize must be a boolean"}
    schema = _wechat_input_schemas()[action]
    if not _basic_validate(raw["input"], schema):
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "invalid wechat input"}
    return build_wechat_family(manager).handle(raw)


WECHAT_SCHEMA = wechat_schema()
WECHAT_ACTIONS = _ACTIONS

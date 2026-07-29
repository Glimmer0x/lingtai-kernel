"""Independent strict LTP-v2 family for programmable Task Card watches."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lingtai.tools.tool_family import ChildTool, ToolFamily

from ... import _skill

_ACTIONS = ("start", "inspect", "retry", "stop", "manual")
_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}


def _object(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "object", "properties": properties, "additionalProperties": False,
    }
    if required:
        value["required"] = required
    return value


def _schemas() -> dict[str, dict[str, Any]]:
    return {
        "start": _object(
            {
                "renderer_path": {"type": "string"},
                "interval_s": {"type": "number", "minimum": 1},
                "timeout_s": {"type": "number", "minimum": 0.1},
                "max_refreshes": {"type": "integer", "minimum": 1, "maximum": 1000},
            },
            required=["renderer_path"],
        ),
        "inspect": _object({"watch_id": {"type": "string"}}, required=["watch_id"]),
        "retry": _object({"watch_id": {"type": "string"}}, required=["watch_id"]),
        "stop": _object({"watch_id": {"type": "string"}}, required=["watch_id"]),
        "manual": _EMPTY,
    }


def _schema_family() -> ToolFamily:
    schemas = _schemas()
    return ToolFamily(
        "task_card", [ChildTool(action, schemas[action], lambda _input: {}) for action in _ACTIONS]
    )


_SCHEMA_FAMILY = _schema_family()


def task_card_schema() -> dict[str, Any]:
    schema = _SCHEMA_FAMILY.build_schema()
    schema["properties"]["action"]["description"] = (
        "Programmable Task Card action. Each action owns a strict input branch; "
        "manual returns the packaged renderer/lifecycle guidance."
    )
    return schema


def _valid(value: Any, schema: Mapping[str, Any]) -> bool:
    if "anyOf" in schema:
        return any(_valid(value, branch) for branch in schema["anyOf"])
    if "oneOf" in schema:
        return sum(_valid(value, branch) for branch in schema["oneOf"]) == 1
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, Mapping):
            return False
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False and set(value) - set(props):
            return False
        if any(name not in value for name in schema.get("required", [])):
            return False
        return all(name not in value or _valid(value[name], child) for name, child in props.items())
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return (
            type(value) is int
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
    if expected == "array":
        return isinstance(value, list)
    return True


def _manual_result() -> dict[str, Any]:
    metadata, body, path = _skill.load_skill("lingtai.mcp_servers.telegram.task_card")
    return {
        "status": "ok",
        "action": "manual",
        "skill": metadata.get("name", "telegram-task-card-manual"),
        "metadata": metadata,
        "path": path,
        "manual": body,
    }


def build_task_card_family(controller: Any | None) -> ToolFamily:
    schemas = _schemas()
    children: list[ChildTool] = []
    for action in _ACTIONS:
        if action == "manual":
            def handler(_input: Mapping[str, Any]) -> dict[str, Any]:
                return _manual_result()
        elif controller is None:
            def handler(_input: Mapping[str, Any]) -> dict[str, Any]:
                return {}
        else:
            def handler(
                input_: Mapping[str, Any], action: str = action, controller: Any = controller
            ) -> dict[str, Any]:
                return controller.handle({"action": action, **dict(input_)})
        children.append(ChildTool(action, schemas[action], handler))
    return ToolFamily("task_card", children)


def handle_task_card(controller: Any | None, args: Mapping[str, Any] | None) -> dict[str, Any]:
    raw = dict(args or {})
    if set(raw) - {"action", "input", "reasoning", "summarize"}:
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "unsupported task_card argument"}
    action = raw.get("action")
    if type(action) is not str or action not in _ACTIONS:
        return {"status": "failed", "error_code": "ACTION_REQUIRED", "message": "invalid task_card action"}
    if "input" not in raw or not isinstance(raw.get("input"), Mapping):
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "input must be an object"}
    if type(raw.get("reasoning")) is not str:
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "reasoning is required"}
    if "summarize" in raw and type(raw["summarize"]) is not bool:
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "summarize must be a boolean"}
    if not _valid(raw["input"], _schemas()[action]):
        return {"status": "failed", "error_code": "INVALID_ARGUMENT", "message": "invalid task_card input"}
    if controller is None and action != "manual":
        return {"status": "failed", "error_code": "UNAVAILABLE", "message": "Task Card controller is host-bound and unavailable"}
    return build_task_card_family(controller).handle(raw)


TASK_CARD_SCHEMA = task_card_schema()
TASK_CARD_ACTIONS = _ACTIONS

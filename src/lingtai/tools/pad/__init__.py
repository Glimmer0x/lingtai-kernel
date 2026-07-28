"""Pad intrinsic — persist pinned reference files for the prompt sketchboard.

The public ``pad`` root has one stateful action, ``append``, plus the reserved
``manual`` signpost. Generic body mutation belongs to ``file.write`` (full
create/overwrite) and ``file.edit`` (exact replacement), and neither file
operation hot-loads the prompt. ``pad.append`` likewise only validates and
persists ``system/pad_append.json``; its list becomes visible after the next
explicit ``context.rebuild`` or passive refresh/molt reconstruction.

``_pad_load`` remains the private canonical composer used by Agent's single
full-context reconstruction path. It is not a public action or compatibility
alias.
"""
from __future__ import annotations

from typing import Any, Mapping

from ._pad import _pad_append, _pad_load  # noqa: F401
from .._manual import load_installed_manual  # noqa: F401
from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import build_manual_child


_APPEND_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": (
                "File paths (text files only) to validate and persist as pinned "
                "read-only pad reference. This NEVER loads or changes the current "
                "system prompt. The new list takes effect only after an explicit "
                "context(action='rebuild') or passive refresh/molt reconstruction. "
                "Pass files=[] to clear the durable list; pass null to inspect it "
                "without changing it. Max 100k tokens total. Paths are relative "
                "to the working directory."
            ),
        },
    },
    "required": ["files"],
    "additionalProperties": False,
}

_CHILD_SPECS: tuple[tuple[str, dict[str, Any], Any], ...] = (
    ("append", _APPEND_INPUT_SCHEMA, _pad_append),
)
ACTION_ORDER: tuple[str, ...] = ("append", "manual")
_DROPPED_ENVELOPE_KEYS = ("_tc_id",)


def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize provider nullable optionals to handler-level absence."""
    return {key: value for key, value in action_input.items() if value is not None}


def _build_children(agent) -> list[ChildTool]:
    def _bind(handler):
        def _dispatch(action_input: Mapping[str, Any]) -> dict:
            return handler(agent, _strip_nulls(action_input))

        return _dispatch

    return [
        ChildTool(name, schema, _bind(handler), title=f"{name} input")
        for name, schema, handler in _CHILD_SPECS
    ] + [build_manual_child(agent, "pad-manual")]


_FAMILY = ToolFamily("pad", _build_children(None))

_ACTION_ENUM_DESCRIPTION = (
    "Required operation on your pad reference list.\n"
    "append: validate and persist the pinned reference list. It does NOT load or "
    "mutate the current prompt; changes take effect only after explicit "
    "context.rebuild or passive refresh/molt reconstruction. Use file.write for "
    "a full system/pad.md rewrite and file.edit for exact replacement; those file "
    "mutations also do not hot-load the prompt.\n"
    "manual: return the installed pad-manual skill without changing disk or prompt."
)


def get_description(lang: str = "en") -> str:
    return (
        "Your pad's pinned read-only references. One public stateful action: "
        "pad(action='append', input={'files': [...]}, reasoning='why') validates "
        "and persists system/pad_append.json but never loads or mutates the current "
        "prompt. Apply durable pad/body/reference changes with one explicit "
        "context.rebuild, or let passive refresh/molt reconstruction apply them. "
        "Use file.write for full system/pad.md create/overwrite and file.edit for "
        "exact replacement. manual returns pad-manual. Results are small; leave "
        "root summarize false."
    )


def get_schema(lang: str = "en") -> dict:
    schema = _FAMILY.build_schema()
    schema["properties"]["action"]["description"] = _ACTION_ENUM_DESCRIPTION
    return schema


def _adapt_manual_result(mcp_result: dict) -> dict:
    flat: dict[str, Any] = {
        "status": mcp_result.get("status", "ok"),
        "manual": mcp_result["content"][0]["text"],
        "manual_path": mcp_result["structuredContent"]["manual_path"],
    }
    if "error" in mcp_result:
        flat["error"] = mcp_result["error"]
    return flat


def handle(agent, args: dict) -> dict:
    """Validate the strict LTP v2 envelope and dispatch one Pad action."""
    raw = dict(args or {})
    for key in _DROPPED_ENVELOPE_KEYS:
        raw.pop(key, None)

    action = raw.get("action")
    result = ToolFamily("pad", _build_children(agent)).handle(raw)
    if action == "manual" and "content" in result:
        return _adapt_manual_result(result)
    if result.get("error_code") == "ACTION_REQUIRED":
        return {
            "error": (
                f"Unknown pad action: {action if action is not None else ''}. "
                f"Must be one of: {', '.join(ACTION_ORDER)}."
            )
        }
    return result


def boot(agent) -> None:
    """Initial internal composition; Agent owns the one post-molt rebuild hook."""
    _pad_load(agent, {})

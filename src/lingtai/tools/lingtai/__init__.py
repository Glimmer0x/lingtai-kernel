"""LingTai intrinsic — a manual-only signpost for the agent's 灵台.

The public root intentionally exposes only the reserved ``manual`` action, like
the skills/knowledge signposts. Durable identity mutation belongs to the generic
``file.write`` / ``file.edit`` operations on ``system/lingtai.md``; those
operations never hot-load the current prompt. An explicit ``context.rebuild``
(or passive refresh/molt reconstruction) applies the durable change.

``_lingtai_load`` remains the private canonical character composer used by the
Agent's one full-context reconstruction path. It is not a public action or
compatibility alias.
"""
from __future__ import annotations

from typing import Any

from ._lingtai import _lingtai_load  # noqa: F401
from .._manual import load_installed_manual  # noqa: F401
from ..tool_family import ToolFamily
from ..tool_family.manual import build_manual_child


ACTION_ORDER: tuple[str, ...] = ("manual",)
_DROPPED_ENVELOPE_KEYS = ("_tc_id",)


def _build_children(agent):
    return [build_manual_child(agent, "lingtai-manual")]


_FAMILY = ToolFamily("lingtai", _build_children(None))

_ACTION_ENUM_DESCRIPTION = (
    "Required operation on your 灵台 signpost. manual: return the installed "
    "lingtai-manual skill without changing disk or prompt. To change durable "
    "system/lingtai.md, use file.write for a full rewrite or file.edit for exact "
    "replacement, then context.rebuild; file mutation never hot-loads the prompt."
)


def get_description(lang: str = "en") -> str:
    return (
        "Your 灵台 (character) signpost. The only public action is "
        "lingtai(action='manual', input={}, reasoning='load identity guidance'), "
        "which returns lingtai-manual and performs no mutation or reload. Use "
        "file.write for a full system/lingtai.md create/overwrite or file.edit for "
        "exact replacement; neither hot-loads the prompt. Apply durable changes "
        "with context.rebuild or passive refresh/molt reconstruction. Leave root "
        "summarize false so exact guidance is retained."
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
    """Validate the strict LTP v2 envelope and dispatch the manual signpost."""
    raw = dict(args or {})
    for key in _DROPPED_ENVELOPE_KEYS:
        raw.pop(key, None)

    action = raw.get("action")
    result = ToolFamily("lingtai", _build_children(agent)).handle(raw)
    if action == "manual" and "content" in result:
        return _adapt_manual_result(result)
    if result.get("error_code") == "ACTION_REQUIRED":
        return {
            "error": (
                f"Unknown lingtai action: {action if action is not None else ''}. "
                "Must be one of: manual."
            )
        }
    return result


def boot(agent) -> None:
    """Initial internal composition; Agent owns the one post-molt rebuild hook."""
    _lingtai_load(agent, {})

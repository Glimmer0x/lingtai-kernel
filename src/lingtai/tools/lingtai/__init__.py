"""LingTai intrinsic — the agent's 灵台: what distinguishes it from every other agent.

Two operations plus the reserved ``manual``, each a canonical
:class:`~lingtai.tools.tool_family.ChildTool` behind the one public ``lingtai``
family root. LingTai was previously addressed through two ``psyche`` leaves; the
split moved the public root only:

    psyche(action="lingtai_update") -> lingtai(action="update")
    psyche(action="lingtai_load")   -> lingtai(action="load")

The handlers in ``_lingtai.py`` are the same functions, unmoved in behavior:
every success payload, error string, log event, and persistence path is exactly
what it was under ``psyche``, including the configured-lingtai reconstruction
authority. Only the model-facing root and the action spelling changed. There is
no compatibility alias — the old ``psyche(action="lingtai_*")`` leaves are simply
unknown actions and fail loudly.

Per-operation behavior, inputs, and result/error shapes live in ``CONTRACT.md``;
the model-facing text lives in the schema descriptions below and in the
``lingtai-manual`` skill. Neither is restated here.

Note on the package name: this is ``lingtai.tools.lingtai``, the tool family.
Absolute imports of the top-level ``lingtai`` package from inside this module
resolve to the top-level package as usual — Python 3 has no implicit relative
imports, so the shared name creates no shadowing.

Sub-modules:
    _lingtai.py — LingTai identity/character management.

Internal:
    boot — boot-time hook: load the identity into the prompt and register the
        post-molt reload. Called from base_agent.__init__ after intrinsics are
        wired, via the generic intrinsic boot loop.
"""
from __future__ import annotations

from typing import Any, Mapping

# --- Re-exports: this package is the ownership home for the lingtai handlers ---
from ._lingtai import _lingtai_update, _lingtai_load  # noqa: F401
from .._manual import load_installed_manual  # noqa: F401
from ..tool_family import ChildTool, ToolFamily
from ..tool_family.manual import build_manual_child


# ---------------------------------------------------------------------------
# Canonical child input schemas — one strict, closed object per action.
# ---------------------------------------------------------------------------
#
# Each action's own ``input`` is declared exactly once here. ``ToolFamily``
# composes the model-facing schema and the dispatch allow-list from these same
# objects, so the two can never drift: the child's canonical name IS the public
# ``action`` value IS the dispatch key.
#
# ``content`` is a destructive FULL REWRITE for ``update``, and keeps its
# pre-split intended/non-empty safety: it is a required, non-nullable string,
# so clearing the identity is the explicit empty string rather than an omission.

_UPDATE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": 'Your full identity — this REPLACES system/lingtai.md entirely, it is not a delta. Carry forward who you have become. Pass an empty string to clear it. Writes and auto-loads immediately; a nonempty configured init `lingtai` value (inline or resolved from `lingtai_file`) replaces it on boot, refresh, and post-molt reconstruction, while absent/empty configuration preserves your self-authored identity.',
        },
    },
    "required": ["content"],
    "additionalProperties": False,
}

_LOAD_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}


# The one canonical child registry: name, canonical input schema, and the
# underlying ``(agent, args)`` handler. Declaring names, order, schemas, and
# handlers in a single place is what makes schema-vs-dispatch drift
# structurally impossible.
#
# Order here is the model-facing ``action`` enum order and the ``input.oneOf``
# branch order. It follows the pre-split psyche leaf order (update, load).
#
# ``manual`` is absent: ``build_manual_child`` owns that child's schema and
# handler, and :func:`_build_children` appends it last.
_CHILD_SPECS: tuple[tuple[str, dict[str, Any], Any], ...] = (
    ("update", _UPDATE_INPUT_SCHEMA, _lingtai_update),
    ("load", _LOAD_INPUT_SCHEMA, _lingtai_load),
)

#: Public action order, derived from the one registry (``manual`` last).
ACTION_ORDER: tuple[str, ...] = tuple(name for name, _s, _h in _CHILD_SPECS) + ("manual",)

#: Transport metadata ``base_agent._dispatch_tool`` injects into every
#: intrinsic's args. No lingtai action consumes it, so — like ``soul`` and
#: ``notification``, and unlike ``psyche``'s molt — it is simply dropped at this
#: family's own Host boundary rather than widening the shared envelope.
_DROPPED_ENVELOPE_KEYS = ("_tc_id",)


def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
    """Drop explicit nulls so "absent" and "null" mean the same downstream.

    Neither lingtai action declares a nullable field today, so this is a
    no-op for every currently valid call. It is kept as the family's one
    normalization seam so a future nullable field cannot silently reach a
    handler that keys off key-absence, matching ``pad``'s identical rule.
    """
    return {key: value for key, value in action_input.items() if value is not None}


def _build_children(agent) -> list[ChildTool]:
    """Build the three children from the one canonical registry.

    ``agent`` may be ``None`` for the module-level schema-only family, whose
    children are never dispatched — only their schemas are read.
    """

    def _bind(handler):
        def _dispatch(action_input: Mapping[str, Any]) -> dict:
            return handler(agent, _strip_nulls(action_input))

        return _dispatch

    return [
        ChildTool(name, schema, _bind(handler), title=f"{name} input")
        for name, schema, handler in _CHILD_SPECS
    ] + [build_manual_child(agent, "lingtai-manual")]


# Composes the model-facing schema. Building it at import time is also the
# registry's duplicate/reserved-name collision check: a collision raises
# ``ToolFamilyError`` here rather than shipping silently. It never dispatches —
# lingtai is an intrinsic *module*, not a per-Agent manager object, so there is
# no instance to hang a family off; ``handle()`` binds one to the passed agent
# per call from this same registry.
_FAMILY = ToolFamily("lingtai", _build_children(None))


# ---------------------------------------------------------------------------
# Schema / description
# ---------------------------------------------------------------------------

#: LingTai's own per-action routing prose. The generic composer writes a neutral
#: "Required operation within the lingtai family." description; the guidance the
#: model actually needs to pick an action replaces it in :func:`get_schema`.
_ACTION_ENUM_DESCRIPTION = (
    'Required operation on your 灵台 — what distinguishes you from every other '
    'agent (system/lingtai.md → the protected `character` prompt section).\n'
    'update: FULL REWRITE of your identity, auto-loads immediately. A nonempty '
    'configured value forces it on reconstruction, while absent/empty '
    'configuration lets it self-evolve.\n'
    'load: re-read system/lingtai.md into your system prompt; read-only.\n'
    'manual: return the installed lingtai-manual skill without performing any '
    'lingtai operation.'
)


def get_description(lang: str = "en") -> str:
    return 'Your 灵台 (character) — the self-authored identity that distinguishes you from every other agent, held in system/lingtai.md and rendered into your protected `character` prompt section. One tool, three actions, each with its own strict input object: lingtai(action=..., input={...}, reasoning=\'why\'). update: REPLACES your whole identity (full rewrite) and auto-loads immediately, while a nonempty configured lingtai value is authoritative on reconstruction and an absent or empty value enables self-evolution. load: re-read the identity into your system prompt. manual: return the installed lingtai-manual skill. Results are small, so leave root summarize false (short-result profile); call manual with summarize=false so the exact procedure is not summarized away.'


def get_schema(lang: str = "en") -> dict:
    # Composed by the generic ToolFamily infra from each child's own canonical
    # ``input_schema`` above, rather than hand-assembled: root ``action`` +
    # per-action ``input`` + required ``reasoning`` + optional ``summarize``,
    # with a root ``allOf`` correlating each ``action`` const to that exact
    # action's ``input`` shape on both the Chat and Responses wires.
    #
    # ``lang`` is accepted for source compatibility and ignored: schema prose
    # is canonical English and language-independent.
    schema = _FAMILY.build_schema()
    schema["properties"]["action"]["description"] = _ACTION_ENUM_DESCRIPTION
    return schema


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _adapt_manual_result(mcp_result: dict) -> dict:
    """Flatten the reserved ``manual`` child's canonical result to lingtai's shape.

    The reserved child is registered unwrapped, so ``ToolFamily.handle()``
    returns its canonical ``content``/``structuredContent`` result verbatim.
    LingTai's public manual result keeps the flat ``load_installed_manual``
    shape (``status``, ``manual``, ``manual_path``, plus ``error`` when
    degraded) that every intrinsic manual action returns, so this Host-owned
    adapter runs strictly *after* dispatch — never inside the child, and never
    as a second envelope around it.
    """
    flat: dict[str, Any] = {
        "status": mcp_result.get("status", "ok"),
        "manual": mcp_result["content"][0]["text"],
        "manual_path": mcp_result["structuredContent"]["manual_path"],
    }
    if "error" in mcp_result:
        flat["error"] = mcp_result["error"]
    return flat


def handle(agent, args: dict) -> dict:
    """Handle the ``lingtai`` family root — validate the envelope, dispatch one action.

    Envelope validation and cross-action rejection belong to the generic
    dispatcher (``tool_family/CONTRACT.md``). This function owns only what is
    lingtai-specific: dropping the intrinsic transport metadata that never
    belongs in the closed root, and the two post-dispatch presentation
    adaptations below.

    ``_tc_id`` is transport metadata ``base_agent._dispatch_tool`` injects into
    EVERY intrinsic's args (capabilities like ``web`` never see it). No lingtai
    action consumes it, so it is dropped here at this family's own Host
    boundary rather than widening the shared ``_ROOT_FIELDS`` set.
    """
    raw = dict(args or {})
    for key in _DROPPED_ENVELOPE_KEYS:
        raw.pop(key, None)

    action = raw.get("action")
    result = ToolFamily("lingtai", _build_children(agent)).handle(raw)

    if action == "manual" and "content" in result:
        return _adapt_manual_result(result)
    if result.get("error_code") == "ACTION_REQUIRED":
        # Preserve a lingtai-shaped unknown-action error rather than the generic
        # envelope failure.
        return {
            "error": (
                f"Unknown lingtai action: {action if action is not None else ''}. "
                f"Must be one of: {', '.join(ACTION_ORDER)}."
            )
        }
    return result


# ---------------------------------------------------------------------------
# Boot hook
# ---------------------------------------------------------------------------


def boot(agent) -> None:
    """Boot-time hook: load the identity into the prompt, register post-molt reload.

    Called from base_agent.__init__ after intrinsics are wired, by the generic
    intrinsic boot loop. LingTai owns its own boot and post-molt reload now that
    it is an independent family; ``psyche`` no longer loads it.
    """
    _lingtai_load(agent, {})
    if not hasattr(agent, "_post_molt_hooks"):
        agent._post_molt_hooks = []
    agent._post_molt_hooks.append(lambda: _lingtai_load(agent, {}))

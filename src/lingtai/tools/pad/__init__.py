"""Pad intrinsic — the agent's system-prompt sketchboard.

Three operations plus the reserved ``manual``, each a canonical
:class:`~lingtai.tools.tool_family.ChildTool` behind the one public ``pad``
family root. Pad was previously addressed through three ``psyche`` leaves; the
split moved the public root only:

    psyche(action="pad_edit")   -> pad(action="edit")
    psyche(action="pad_load")   -> pad(action="load")
    psyche(action="pad_append") -> pad(action="append")

The handlers in ``_pad.py`` are the same functions, unmoved in behavior: every
success payload, error string, log event, and persistence path is exactly what
it was under ``psyche``. Only the model-facing root and the action spelling
changed. There is no compatibility alias — the old ``psyche(action="pad_*")``
leaves are simply unknown actions and fail loudly.

Per-operation behavior, inputs, and result/error shapes live in ``CONTRACT.md``;
the model-facing text lives in the schema descriptions below and in the
``pad-manual`` skill. Neither is restated here.

Action separation is structural: :data:`_CHILD_SPECS` is the single registry of
name, schema, and handler, so the model-facing schema and dispatch are generated
from one source and cannot drift.

Sub-modules:
    _pad.py — Pad CRUD and append-file management.

Internal:
    boot — boot-time hook: load the pad into the prompt and register the
        post-molt reload. Called from base_agent.__init__ after intrinsics are
        wired, via the generic intrinsic boot loop.
"""
from __future__ import annotations

from typing import Any, Mapping

# --- Re-exports: this package is the ownership home for the pad handlers ---
from ._pad import _pad_edit, _pad_load, _pad_append  # noqa: F401
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
# ``content`` is a destructive FULL REWRITE for ``edit``. It keeps the
# pre-split "intended, non-empty" safety: the nullable representation below
# plus ``_strip_nulls`` reproduces the exact ``"content" not in args``
# distinction the handler keys off, so a bare ``edit`` with neither content nor
# files is still refused rather than silently clearing the pad.

_EDIT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {
            "type": ["string", "null"],
            "description": 'Written as-is to system/pad.md. This REPLACES the pad entirely — a full rewrite, not an append. Pass an empty string to clear the pad explicitly; pass null to supply only `files`. Providing neither content nor files is refused.',
        },
        "files": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": 'Optional file paths (text files only) whose contents are imported into the pad body as [file-N] blocks at edit time. Distinct from pad(action="append"), which pins files as re-read read-only reference. Paths relative to working directory. Pass null when not importing files.',
        },
    },
    "required": ["content", "files"],
    "additionalProperties": False,
}

_LOAD_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

_APPEND_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": 'File paths (text files only) pinned as read-only reference in your system prompt — re-read on every load including after molt. Pass files=[] to clear the pin list. Pass null to read the current list without changing it. Max 100k tokens total. Paths relative to working directory. See pad-manual for detailed usage.',
        },
    },
    "required": ["files"],
    "additionalProperties": False,
}


# The one canonical child registry: name, canonical input schema, and the
# underlying ``(agent, args)`` handler. Declaring names, order, schemas, and
# handlers in a single place is what makes schema-vs-dispatch drift
# structurally impossible.
#
# Order here is the model-facing ``action`` enum order and the
# ``input.oneOf`` branch order. It follows the pre-split psyche leaf order
# (edit, load, append) so the surface reads the way it always did.
#
# ``manual`` is absent: ``build_manual_child`` owns that child's schema and
# handler, and :func:`_build_children` appends it last.
_CHILD_SPECS: tuple[tuple[str, dict[str, Any], Any], ...] = (
    ("edit", _EDIT_INPUT_SCHEMA, _pad_edit),
    ("load", _LOAD_INPUT_SCHEMA, _pad_load),
    ("append", _APPEND_INPUT_SCHEMA, _pad_append),
)

#: Public action order, derived from the one registry (``manual`` last).
ACTION_ORDER: tuple[str, ...] = tuple(name for name, _s, _h in _CHILD_SPECS) + ("manual",)

#: Transport metadata ``base_agent._dispatch_tool`` injects into every
#: intrinsic's args. No pad action consumes it, so — like ``soul`` and
#: ``notification``, and unlike ``psyche``'s molt — it is simply dropped at this
#: family's own Host boundary rather than widening the shared envelope.
_DROPPED_ENVELOPE_KEYS = ("_tc_id",)


def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
    """Drop explicit nulls so "absent" and "null" mean the same downstream.

    Strict provider schemas express an optional field as a REQUIRED nullable
    property, so the model must send ``{"content": null, "files": [...]}`` for
    a files-only edit. The handlers key off ``"content" not in args`` /
    ``args.get("files") is None``; stripping nulls here reproduces that exact
    behavior — including ``edit``'s "Provide content ..., files, or both."
    refusal and ``append``'s null-means-read query — without touching the
    handlers themselves.
    """
    return {key: value for key, value in action_input.items() if value is not None}


def _build_children(agent) -> list[ChildTool]:
    """Build the four children from the one canonical registry.

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
    ] + [build_manual_child(agent, "pad-manual")]


# Composes the model-facing schema. Building it at import time is also the
# registry's duplicate/reserved-name collision check: a collision raises
# ``ToolFamilyError`` here rather than shipping silently. It never dispatches —
# pad is an intrinsic *module*, not a per-Agent manager object, so there is no
# instance to hang a family off; ``handle()`` binds one to the passed agent per
# call from this same registry.
_FAMILY = ToolFamily("pad", _build_children(None))


# ---------------------------------------------------------------------------
# Schema / description
# ---------------------------------------------------------------------------

#: Pad's own per-action routing prose. The generic composer writes a neutral
#: "Required operation within the pad family." description; the guidance the
#: model actually needs to pick an action replaces it in :func:`get_schema`.
_ACTION_ENUM_DESCRIPTION = (
    'Required operation on your pad — the sketchboard in your system prompt '
    '(system/pad.md).\n'
    'edit: FULL REWRITE of the pad body, auto-loads immediately.\n'
    'load: re-read system/pad.md and the pinned reference files into your '
    'system prompt; read-only.\n'
    'append: pin files as re-read read-only reference alongside the pad.\n'
    'manual: return the installed pad-manual skill without performing any pad '
    'operation.'
)


def get_description(lang: str = "en") -> str:
    return 'Your pad — the sketchboard in your system prompt (system/pad.md): plans, tasks, notes, and pointers to where the substance lives. One tool, four actions, each with its own strict input object: pad(action=..., input={...}, reasoning=\'why\'). edit: REPLACES the whole pad (full rewrite) and auto-loads. load: re-read the pad and its pinned reference files. append: pin files as read-only reference re-read on every load, including after molt. manual: return the installed pad-manual skill. Results are small, so leave root summarize false (short-result profile); call manual with summarize=false so the exact procedure is not summarized away.'


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
    """Flatten the reserved ``manual`` child's canonical result to pad's shape.

    The reserved child is registered unwrapped, so ``ToolFamily.handle()``
    returns its canonical ``content``/``structuredContent`` result verbatim.
    Pad's public manual result keeps the flat ``load_installed_manual`` shape
    (``status``, ``manual``, ``manual_path``, plus ``error`` when degraded) that
    every intrinsic manual action returns, so this Host-owned adapter runs
    strictly *after* dispatch — never inside the child, and never as a second
    envelope around it.
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
    """Handle the ``pad`` family root — validate the envelope, dispatch one action.

    Envelope validation and cross-action rejection belong to the generic
    dispatcher (``tool_family/CONTRACT.md``). This function owns only what is
    pad-specific: dropping the intrinsic transport metadata that never belongs
    in the closed root, and the two post-dispatch presentation adaptations
    below.

    ``_tc_id`` is transport metadata ``base_agent._dispatch_tool`` injects into
    EVERY intrinsic's args (capabilities like ``web`` never see it). No pad
    action consumes it, so it is dropped here at this family's own Host
    boundary rather than widening the shared ``_ROOT_FIELDS`` set.
    """
    raw = dict(args or {})
    for key in _DROPPED_ENVELOPE_KEYS:
        raw.pop(key, None)

    action = raw.get("action")
    result = ToolFamily("pad", _build_children(agent)).handle(raw)

    if action == "manual" and "content" in result:
        return _adapt_manual_result(result)
    if result.get("error_code") == "ACTION_REQUIRED":
        # Preserve a pad-shaped unknown-action error rather than the generic
        # envelope failure.
        return {
            "error": (
                f"Unknown pad action: {action if action is not None else ''}. "
                f"Must be one of: {', '.join(ACTION_ORDER)}."
            )
        }
    return result


# ---------------------------------------------------------------------------
# Boot hook
# ---------------------------------------------------------------------------


def boot(agent) -> None:
    """Boot-time hook: load the pad into the prompt, register post-molt reload.

    Called from base_agent.__init__ after intrinsics are wired, by the generic
    intrinsic boot loop. Pad owns its own boot and post-molt reload now that it
    is an independent family; ``psyche`` no longer loads it.
    """
    _pad_load(agent, {})
    if not hasattr(agent, "_post_molt_hooks"):
        agent._post_molt_hooks = []
    agent._post_molt_hooks.append(lambda: _pad_load(agent, {}))

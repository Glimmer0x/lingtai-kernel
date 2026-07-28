"""Psyche intrinsic — context lifecycle and the agent's name.

Three operations plus the reserved ``manual``, each a canonical
:class:`~lingtai.tools.tool_family.ChildTool` behind the one public ``psyche``
family root:

    name set      -> name_set        context molt -> context_molt
    name nickname -> name_nickname

``pad`` and ``lingtai`` were split out of this family into their own
model-visible roots (``lingtai.tools.pad`` / ``lingtai.tools.lingtai``): they
are concepts parallel to ``knowledge`` and ``skills``, not psyche leaves. The
five former leaves (``pad_edit``/``pad_load``/``pad_append``/
``lingtai_update``/``lingtai_load``) are gone with no compatibility alias —
they are unknown actions here and fail loudly. The remaining three action
names and every one of their semantics are unchanged by that split; whether
psyche itself should later shrink, be renamed, or disappear is a separate
open design question this change deliberately does not answer.

Per-operation behavior, inputs, and result/error shapes live in
``CONTRACT.md``; the model-facing text lives in the schema descriptions below
and in the ``psyche-manual`` skill. Neither is restated here.

Action separation is structural: :data:`_CHILD_SPECS` is the single registry
of name, schema, and handler, so the model-facing schema and dispatch are
generated from one source and cannot drift. Every success payload, error
string, log event, and persistence path for the retained actions is exactly
what it was before the split.

Sub-modules:
    _snapshots.py — Snapshot and summary persistence for the molt machinery.
    _molt.py      — Context molt core, name handlers, system-initiated molt.

Internal:
    boot — boot-time hook: register the post-molt prompt-reload hook. Called
        from base_agent.__init__ after intrinsics are wired. Pad and lingtai
        each own their own boot and post-molt reload now.
"""
from __future__ import annotations

from typing import Any, Mapping

# --- Re-exports from sub-modules for backward compatibility ---

# Snapshots (used by consultation, inquiry, etc.)
from ._snapshots import SNAPSHOT_SCHEMA_VERSION, _write_molt_snapshot, _write_molt_summary  # noqa: F401

# Molt (the public surface)
from ._molt import _context_molt, _name_set, _name_nickname, context_forget  # noqa: F401
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
# The property descriptions are carried over from the pre-migration flat
# schema; only their location changed (one shared flat root -> the one action
# that actually consumes them). That relocation is the whole point of the
# migration: ``name_set`` no longer advertises ``keep_tool_calls``.

_CONTEXT_MOLT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": 'Your session retrospective (~10,000 tokens). Write as a record — what happened, what you learned, what remains. The four stores must be tended BEFORE molt. Saved to `system/summaries/molt_<count>_<ts>.md` and replayed to the next you. See psyche-manual for full writing guidance. This is domain input the molt itself consumes, not the root `summarize` post-processing control.',
        },
        "session_journal_path": {
            "type": "string",
            "description": 'REQUIRED. The path to the session-journal entry you wrote for the just-finished segment BEFORE molting: knowledge/session-journal/<entry>/KNOWLEDGE.md (a per-segment sub-entry, NOT the parent index). Must be inside your workdir, exist, be non-empty UTF-8, have valid YAML frontmatter with `name` and `description`, and identify itself as session knowledge via `type: session-journal` or `session_journal: true`. The molt is refused before any context is shed if this is missing or invalid. See psyche-manual §4.',
        },
        "keep_tool_calls": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": 'Optional list of tool-call IDs to replay across the molt, in your chosen order. If any ID is not found, molt is refused before anything is shed. Keep short — durable stores are primary persistence. Pass null to keep none. See psyche-manual.',
        },
        "keep_last": {
            "type": ["integer", "null"],
            "description": 'Optional number of recent conversation entries to replay into the fresh session (default: 20 when null). Pass 0 to archive everything. Overlapping entries with keep_tool_calls are deduplicated. See psyche-manual.',
        },
    },
    "required": ["summary", "session_journal_path", "keep_tool_calls", "keep_last"],
    "additionalProperties": False,
}

_NAME_SET_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": 'Your chosen true name (真名). Set ONCE and immutable thereafter — a second name_set is refused. Use name_nickname for a changeable display name.',
        },
    },
    "required": ["content"],
    "additionalProperties": False,
}

_NAME_NICKNAME_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": 'Your chosen nickname (别名) — mutable, unlike the true name. Pass an empty string to clear it.',
        },
    },
    "required": ["content"],
    "additionalProperties": False,
}


# The one canonical child registry: name, canonical input schema, and the
# underlying ``(agent, args)`` handler carried over verbatim from the
# pre-migration ``_DISPATCH`` table. Declaring names, order, schemas, and
# handlers in a single place is what makes schema-vs-dispatch drift
# structurally impossible — there is no second list to forget to update, so a
# child can never be schema-advertised but dispatch-rejected.
#
# Order here is the model-facing ``action`` enum order and the
# ``input.oneOf`` branch order. It preserves the relative order the retained
# actions have always had (context, then name), with the five split-out
# pad/lingtai leaves removed rather than reordered.
#
# ``manual`` is absent: ``build_manual_child`` owns that child's schema and
# handler, and :func:`_build_children` appends it last.
_CHILD_SPECS: tuple[tuple[str, dict[str, Any], Any], ...] = (
    ("context_molt", _CONTEXT_MOLT_INPUT_SCHEMA, _context_molt),
    ("name_set", _NAME_SET_INPUT_SCHEMA, _name_set),
    ("name_nickname", _NAME_NICKNAME_INPUT_SCHEMA, _name_nickname),
)

#: Public action order, derived from the one registry (``manual`` last).
ACTION_ORDER: tuple[str, ...] = tuple(name for name, _s, _h in _CHILD_SPECS) + ("manual",)

#: Envelope metadata the family threads to a handler out-of-band rather than
#: as action ``input``. ``_tc_id`` is the wire tool_use_id
#: ``base_agent._dispatch_tool`` injects into every intrinsic's args;
#: ``context_molt`` is the one operation that genuinely *consumes* it (it
#: locates the molt's own ToolCallBlock in the live interface to replay it), so
#: unlike ``soul``/``notification`` — which merely drop it — psyche strips it
#: from the closed root and hands it to that one handler directly. Root
#: ``reasoning``/``_reasoning`` is threaded the same way for the post-molt
#: reminder, exactly as ``avatar`` threads its spawn mission brief.
_MOLT_ENVELOPE_KEYS = ("_tc_id", "_reasoning", "reasoning", "_initiator")


def _strip_nulls(action_input: Mapping[str, Any]) -> dict[str, Any]:
    """Drop explicit nulls so "absent" and "null" mean the same downstream.

    Strict provider schemas express an optional field as a REQUIRED nullable
    property, so the model must send ``{"content": null, "files": [...]}`` for
    a files-only pad edit. The pre-migration handlers keyed off
    ``"content" not in args`` / ``args.get("files") is None``; stripping nulls
    here reproduces that exact behavior — including ``pad_edit``'s "Provide
    content ..., files, or both." refusal and ``pad_append``'s null-means-read
    query — without touching the handlers themselves.
    """
    return {key: value for key, value in action_input.items() if value is not None}


def _build_children(agent, envelope: Mapping[str, Any] | None = None) -> list[ChildTool]:
    """Build the four children from the one canonical registry.

    ``agent`` may be ``None`` for the module-level schema-only family, whose
    children are never dispatched — only their schemas are read.

    ``envelope`` carries the out-of-band metadata keys in
    :data:`_MOLT_ENVELOPE_KEYS`. ``ToolFamily`` correctly passes no envelope
    field to any child, so the one handler that consumes transport metadata
    (``context_molt``, which needs ``_tc_id`` to locate and replay its own
    ToolCallBlock) receives it here, merged beneath the validated ``input``
    rather than smuggled through it.
    """
    extra = dict(envelope or {})

    def _bind(handler, name: str):
        def _dispatch(action_input: Mapping[str, Any]) -> dict:
            args = _strip_nulls(action_input)
            if name == "context_molt":
                # Envelope metadata never overwrites validated action input.
                for key, value in extra.items():
                    args.setdefault(key, value)
            return handler(agent, args)

        return _dispatch

    return [
        ChildTool(name, schema, _bind(handler, name), title=f"{name} input")
        for name, schema, handler in _CHILD_SPECS
    ] + [build_manual_child(agent, "psyche-manual")]


# Composes the model-facing schema. Building it at import time is also the
# registry's duplicate/reserved-name collision check: a collision raises
# ``ToolFamilyError`` here rather than shipping silently. It never dispatches —
# psyche is an intrinsic *module*, not a per-Agent manager object, so there is
# no instance to hang a family off; ``handle()`` binds one to the passed agent
# per call from this same registry.
_FAMILY = ToolFamily("psyche", _build_children(None))


# ---------------------------------------------------------------------------
# Schema / description
# ---------------------------------------------------------------------------

#: Psyche's own per-action routing prose. The generic composer writes a neutral
#: "Required operation within the psyche family." description; the object-level
#: guidance the model actually needs to pick an action replaces it in
#: :func:`get_schema` rather than being lost.
_ACTION_ENUM_DESCRIPTION = (
    'Required operation. '
    'context_molt: shed your conversation context, keep the durable stores. '
    'Requires `summary` and a valid `session_journal_path` — tend the four '
    'stores BEFORE molting. See psyche-manual.\n'
    'name_set: your true name, set once and immutable. name_nickname: your '
    'display name, mutable.\n'
    'manual: return the installed psyche-manual skill without performing any '
    'psyche operation.\n'
    'Your 灵台 and your pad are separate tools: use lingtai(...) and pad(...).'
)


def get_description(lang: str = "en") -> str:
    return 'Name and context management. One tool, four actions, each with its own strict input object: psyche(action=..., input={...}, reasoning=\'why\'). context_molt: molt (凝蜕) — shed conversation, keep stores; requires a written session journal. name_set: true name (once). name_nickname: display name (mutable). manual: return the installed psyche-manual skill. Your 灵台 (character) and your pad are separate tools — use lingtai(action=\'update\'|\'load\') and pad(action=\'edit\'|\'load\'|\'append\'). Results are small, so leave root summarize false (short-result profile); call manual with summarize=false so the exact molt procedure is not summarized away.'


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
    """Flatten the reserved ``manual`` child's canonical result to psyche's shape.

    The reserved child is registered unwrapped, so ``ToolFamily.handle()``
    returns its canonical ``content``/``structuredContent`` result verbatim.
    Psyche's public manual result predates that generic contract and must stay
    the flat ``load_installed_manual`` shape (``status``, ``manual``,
    ``manual_path``, plus ``error`` when degraded), so this Host-owned adapter
    runs strictly *after* dispatch — never inside the child, and never as a
    second envelope around it.
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
    """Handle the ``psyche`` family root — validate the envelope, dispatch one action.

    Envelope validation and cross-action rejection belong to the generic
    dispatcher (``tool_family/CONTRACT.md``). This function owns only what is
    psyche-specific: lifting the intrinsic transport/audit metadata out of the
    closed root, and the two post-dispatch presentation adaptations below.

    ``_tc_id`` is transport metadata ``base_agent._dispatch_tool`` injects into
    EVERY intrinsic's args (capabilities like ``web`` never see it). Psyche is
    the one family that genuinely *consumes* it — ``context_molt`` locates the
    molt's own ToolCallBlock by that wire id to replay it into the fresh
    session — so it is stripped here, at this family's own Host boundary, and
    threaded to that single handler out-of-band. The shared ``_ROOT_FIELDS``
    set is not widened for it, and no other action can observe it.
    """
    raw = dict(args or {})
    envelope = {key: raw.pop(key) for key in _MOLT_ENVELOPE_KEYS if key in raw}
    # ``reasoning``/``_reasoning`` remain admitted root fields for the generic
    # dispatcher, so put back the public spelling it knows about; only the
    # molt handler sees the copy in ``envelope``.
    for key in ("reasoning", "_reasoning"):
        if key in envelope:
            raw[key] = envelope[key]

    action = raw.get("action")
    result = ToolFamily("psyche", _build_children(agent, envelope)).handle(raw)

    if action == "manual" and "content" in result:
        return _adapt_manual_result(result)
    if result.get("error_code") == "ACTION_REQUIRED":
        # Preserve a psyche-shaped unknown-action error rather than the
        # generic envelope failure.
        return {
            "error": (
                f"Unknown psyche action: {action if action is not None else ''}. "
                f"Must be one of: {', '.join(ACTION_ORDER)}."
            )
        }
    return result


# ---------------------------------------------------------------------------
# Boot hook
# ---------------------------------------------------------------------------
#
# Psyche no longer defines ``boot``. Its only boot-time work was loading the
# pad and the lingtai identity into the prompt and registering their post-molt
# reload; both moved with their families to ``lingtai.tools.pad.boot`` and
# ``lingtai.tools.lingtai.boot``, which the same generic intrinsic boot loop
# (``base_agent.__init__``) runs. Psyche's own retained actions have no
# boot-time state to establish, so an empty passthrough hook would be
# ceremony rather than behavior.

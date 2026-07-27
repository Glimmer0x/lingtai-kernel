"""Psyche intrinsic — bare essentials of agent self.

Eight operations plus the reserved ``manual``, each a canonical
:class:`~lingtai.tools.tool_family.ChildTool` behind the one public ``psyche``
family root. The pre-migration ``(object, action)`` matrix is preserved
verbatim as flat action names — one action per former ``(object, action)``
pair, the same collapse ``notification`` made for its three atomic dismiss
verbs:

    lingtai update   -> lingtai_update      pad edit   -> pad_edit
    lingtai load     -> lingtai_load        pad load   -> pad_load
    name set         -> name_set            pad append -> pad_append
    name nickname    -> name_nickname       context molt -> context_molt

Per-operation behavior, inputs, and result/error shapes live in
``CONTRACT.md``; the model-facing text lives in the schema descriptions below
and in the ``psyche-manual`` skill. Neither is restated here.

Action separation is structural: :data:`_CHILD_SPECS` is the single registry
of name, schema, and handler, so the model-facing schema and dispatch are
generated from one source and cannot drift. Every success payload, error
string, log event, and persistence path is exactly what it was before the
migration — only the argument *shape* moved from a flat ``object``/``action``
root into ``action`` + per-action ``input``.

Sub-modules:
    _snapshots.py — Snapshot and summary persistence for the molt machinery.
    _pad.py       — Pad CRUD and append-file management.
    _lingtai.py   — Lingtai identity/character management.
    _molt.py      — Context molt core, name handlers, system-initiated molt.

Internal:
    boot — boot-time hook: load lingtai + pad into prompt, register post-molt
        reload. Called from base_agent.__init__ after intrinsics are wired.
"""
from __future__ import annotations

from typing import Any, Mapping

# --- Re-exports from sub-modules for backward compatibility ---

# Snapshots (used by consultation, inquiry, etc.)
from ._snapshots import SNAPSHOT_SCHEMA_VERSION, _write_molt_snapshot, _write_molt_summary  # noqa: F401

# Pad (used by boot, and cross-referenced by lingtai/append)
from ._pad import _pad_edit, _pad_load, _pad_append  # noqa: F401

# Lingtai (used by boot, and cross-referenced by pad)
from ._lingtai import _lingtai_update, _lingtai_load  # noqa: F401

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
# migration: ``pad_load`` no longer advertises ``summary``, and ``name_set``
# no longer advertises ``keep_tool_calls``.
#
# ``content`` is a destructive FULL REWRITE for ``lingtai_update`` and
# ``pad_edit``. Both keep the pre-migration "intended, non-empty" safety: the
# nullable representation below plus ``_strip_nulls`` reproduces the exact
# ``"content" not in args`` distinction the handlers key off, so a bare
# ``pad_edit`` with neither content nor files is still refused rather than
# silently clearing the pad.

_LINGTAI_UPDATE_INPUT_SCHEMA: dict[str, Any] = {
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

_LINGTAI_LOAD_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

_PAD_EDIT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "content": {
            "type": ["string", "null"],
            "description": 'Written as-is to system/pad.md. This REPLACES the pad entirely — a full rewrite, not an append. Pass an empty string to clear the pad explicitly; pass null to supply only `files`. Providing neither content nor files is refused.',
        },
        "files": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": 'Optional file paths (text files only) whose contents are imported into the pad body as [file-N] blocks at edit time. Distinct from pad_append, which pins files as re-read read-only reference. Paths relative to working directory. Pass null when not importing files.',
        },
    },
    "required": ["content", "files"],
    "additionalProperties": False,
}

_PAD_LOAD_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

_PAD_APPEND_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "files": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": 'File paths (text files only) pinned as read-only reference in your system prompt — re-read on every load including after molt. Pass files=[] to clear the pin list. Pass null to read the current list without changing it. Max 100k tokens total. Paths relative to working directory. See psyche-manual for detailed usage.',
        },
    },
    "required": ["files"],
    "additionalProperties": False,
}

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
# ``input.oneOf`` branch order. It follows the pre-migration ``_VALID_ACTIONS``
# object order (lingtai, pad, context, name) so the surface reads the same way
# it always did.
#
# ``manual`` is absent: ``build_manual_child`` owns that child's schema and
# handler, and :func:`_build_children` appends it last.
_CHILD_SPECS: tuple[tuple[str, dict[str, Any], Any], ...] = (
    ("lingtai_update", _LINGTAI_UPDATE_INPUT_SCHEMA, _lingtai_update),
    ("lingtai_load", _LINGTAI_LOAD_INPUT_SCHEMA, _lingtai_load),
    ("pad_edit", _PAD_EDIT_INPUT_SCHEMA, _pad_edit),
    ("pad_load", _PAD_LOAD_INPUT_SCHEMA, _pad_load),
    ("pad_append", _PAD_APPEND_INPUT_SCHEMA, _pad_append),
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
    """Build the nine children from the one canonical registry.

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
    'Required operation. lingtai_update | lingtai_load: your 灵台 — what '
    'distinguishes you from every other agent. lingtai_update is a FULL '
    'REWRITE and auto-loads; a configured nonempty value forces it on '
    'reconstruction, while absent/empty configuration lets it self-evolve.\n'
    'pad_edit | pad_load | pad_append: your sketchboard in your system prompt '
    '(system/pad.md). pad_edit is a FULL REWRITE and auto-loads; pad_append '
    'pins files as re-read read-only reference.\n'
    'context_molt: shed your conversation context, keep the durable stores. '
    'Requires `summary` and a valid `session_journal_path` — tend the four '
    'stores BEFORE molting. See psyche-manual.\n'
    'name_set: your true name, set once and immutable. name_nickname: your '
    'display name, mutable.\n'
    'manual: return the installed psyche-manual skill without performing any '
    'psyche operation.'
)


def get_description(lang: str = "en") -> str:
    return 'Identity, pad, name, and context management. One tool, nine actions, each with its own strict input object: psyche(action=..., input={...}, reasoning=\'why\'). lingtai_update/lingtai_load: your 灵台 (character) — psyche updates it immediately, while a nonempty configured lingtai value is authoritative on reconstruction and an absent or empty value enables self-evolution. lingtai_update REPLACES your whole identity. pad_edit/pad_load/pad_append: system-prompt sketchboard (system/pad.md) — plans, tasks, notes; pad_edit REPLACES the whole pad, pad_append pins read-only reference files. context_molt: molt (凝蜕) — shed conversation, keep stores; requires a written session journal. name_set: true name (once). name_nickname: display name (mutable). manual: return the installed psyche-manual skill. Results are small, so leave root summarize false (short-result profile); call manual with summarize=false so the exact molt procedure is not summarized away.'


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


def boot(agent) -> None:
    """Boot-time hook: load lingtai + pad into the prompt, register post-molt
    reload. Called from base_agent.__init__ after intrinsics are wired."""
    _pad_load(agent, {})
    _lingtai_load(agent, {})
    if not hasattr(agent, "_post_molt_hooks"):
        agent._post_molt_hooks = []
    agent._post_molt_hooks.append(
        lambda: (_lingtai_load(agent, {}), _pad_load(agent, {}))
    )

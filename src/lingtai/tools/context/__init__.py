"""Context intrinsic — the department that owns the agent's context.

An LTP v2 family (``../CONTRACT.md``): one model-facing root ``context`` with
four fixed canonical action children, each owning its own strict ``input``
object::

    molt      -> shed the conversation, keep the durable stores
    summarize -> record compact replacements in runtime history (record-only)
    rebuild   -> recompose the full prompt, apply summaries, replay provider context
    manual    -> return the installed context-manual skill

This package replaces the former ``psyche`` family, which mixed two unrelated
concerns behind one root: the context lifecycle (molt) and the agent's name.
``psyche`` no longer exists at any model-visible or registry level, and there
is no compatibility alias — ``psyche(...)`` is an unknown tool and the two name
actions now live on ``system`` (``lingtai.tools.system.name``). What arrived
here from elsewhere is the context-hygiene half of ``system``: the public
``system(action='summarize')`` action became the two explicit actions
``context.summarize`` and ``context.rebuild``, and is gone from ``system``.

The molt semantics are moved, not redesigned: summary/session-journal gating,
refusal-before-shed, keep_tool_calls/keep_last, archive/snapshot/rebuild,
``_tc_id`` transport handling, the post-molt notification, forced system molt,
and every durable-store path are exactly what they were. Only the public root
and action name changed (``psyche.context_molt`` -> ``context.molt``). The
durable molt *event* key is deliberately NOT renamed; see
``kernel/agent_session.py`` ``MOLT_BOUNDARY_EVENT``.

Two names spelled ``summarize`` coexist at different envelope levels, and they
are unrelated:

  * ``context(action='summarize')`` — this family's record-only ACTION;
  * the optional root ``summarize`` boolean — the cross-cutting a-priori
    result-summarization presentation control every LTP v2 family advertises
    (``kernel/tool_result_summary.py``).

The root boolean is stripped by the generic dispatcher and is never domain
input; no child here declares a ``summarize`` property. ``context.summarize``
records and never rebuilds; ``context.rebuild`` is the only active operation
that first recomposes every canonical prompt source, then applies pending/new
summaries, then requests provider replay. The public action — not a boolean —
is the discriminator.

Per-action behavior, inputs, and result/error shapes live in ``CONTRACT.md``;
the model-facing text lives in the schema descriptions below and in the
``context-manual`` skill. Neither is restated here.

Sub-modules:
    _snapshots.py — Snapshot and summary persistence for the molt machinery.
    _molt.py      — Context molt core and the system-initiated forced molt.
    _plugin.py    — package-local model-facing schema/dispatch/manual surface.
"""
from __future__ import annotations

from typing import Any

# --- Re-exports from sub-modules for backward compatibility ---

# Snapshots (used by consultation, inquiry, etc.)
from ._snapshots import SNAPSHOT_SCHEMA_VERSION, _write_molt_snapshot, _write_molt_summary  # noqa: F401

# Molt (the public surface)
from ._molt import _context_molt, context_forget  # noqa: F401
from ..tool_family import TRIGGER_UNSUPPORTED_INPUT_FIELD, DiagnosticDescriptor
from ._plugin import ContextToolPlugin

# The summarize/rebuild engine. It stays in ``system/summarize.py`` — moving
# the ~700-line engine and its marker constants is not required to move public
# ownership, and ``kernel``/adapters already import ``SUMMARIZE_MARKER`` and
# ``mark_pending_summaries_done`` from there for the forced-rebuild path. This
# family owns the public actions; that module remains the private engine.
from ..system.summarize import _summarize as _summarize_engine


# ---------------------------------------------------------------------------
# Canonical child input schemas — one strict, closed object per action.
# ---------------------------------------------------------------------------
#
# Each action's own ``input`` is declared exactly once here. ``ToolFamily``
# composes the model-facing schema and the dispatch allow-list from these same
# objects, so the two can never drift: the child's canonical name IS the public
# ``action`` value IS the dispatch key.

_MOLT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {
            "type": "string",
            "description": 'Your session retrospective (~10,000 tokens). Write as a record — what happened, what you learned, what remains. The four stores must be tended BEFORE molt. Saved to `system/summaries/molt_<count>_<ts>.md` and replayed to the next you. See context-manual for full writing guidance. This is domain input the molt itself consumes, not the root `summarize` post-processing control.',
        },
        "session_journal_path": {
            "type": "string",
            "description": 'REQUIRED. The path to the session-journal entry you wrote for the just-finished segment BEFORE molting: knowledge/session-journal/<entry>/KNOWLEDGE.md (a per-segment sub-entry, NOT the parent index). Must be inside your workdir, exist, be non-empty UTF-8, have valid YAML frontmatter with `name` and `description`, and identify itself as session knowledge via `type: session-journal` or `session_journal: true`. The molt is refused before any context is shed if this is missing or invalid. See context-manual §4.',
        },
        "keep_tool_calls": {
            "type": ["array", "null"],
            "items": {"type": "string"},
            "description": 'Optional list of tool-call IDs to replay across the molt, in your chosen order. If any ID is not found, molt is refused before anything is shed. Keep short — durable stores are primary persistence. Pass null to keep none. See context-manual.',
        },
        "keep_last": {
            "type": ["integer", "null"],
            "description": 'Optional requested minimum number of recent conversation entries to replay into the fresh session (default: 20 when null). The retained suffix may contain more entries when needed to preserve one adjacent assistant tool-call/result batch whole. Pass 0 to archive everything. Overlapping entries with keep_tool_calls are deduplicated. See context-manual.',
        },
    },
    "required": ["summary", "session_journal_path", "keep_tool_calls", "keep_last"],
    "additionalProperties": False,
}

# ``molt``'s own static, mechanical diagnostic for a foreign ``input`` field
# (cross-action, e.g. a ``summarize``/``rebuild`` key, or wholly unknown, e.g.
# a smuggled ``files``): declared once, adjacent to ``_MOLT_INPUT_SCHEMA``,
# per ``tool_family/CONTRACT.md`` "Diagnostics sidecar". The generic
# dispatcher only ever supplies the structural ``location`` around this
# verbatim text — it does not (and must not) claim `session_journal_path`
# has to be relative; the existing in-workdir-absolute-normalizes-to-relative
# policy is unchanged and unrelated to this diagnostic.
_MOLT_UNSUPPORTED_INPUT_DIAGNOSTIC = DiagnosticDescriptor(
    code="CTX_MOLT_UNSUPPORTED_INPUT_FIELD",
    expected_form=(
        "an input object containing only summary, session_journal_path, "
        "keep_tool_calls, and keep_last"
    ),
    reason="molt rejects foreign action input before it can shed context",
    fix="remove the foreign field or choose the action that owns it",
)

#: Per-child diagnostic sidecars, keyed by child name then structural
#: trigger. Only ``molt`` opts in today; a child absent here (``summarize``,
#: ``rebuild``, ``manual``) gets exactly the generic dispatcher's legacy
#: three-key failure for a foreign ``input`` field, unchanged.
_CHILD_DIAGNOSTICS: dict[str, Mapping[str, DiagnosticDescriptor]] = {
    "molt": {TRIGGER_UNSUPPORTED_INPUT_FIELD: _MOLT_UNSUPPORTED_INPUT_DIAGNOSTIC},
}

#: One item of the summarize/rebuild ``items`` array. Declared once and reused
#: by both schemas below so the two branches cannot drift.
_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool_call_id": {
            "type": "string",
            "description": "The id of the prior tool-result block to summarize.",
        },
        "summary": {
            "type": "string",
            "description": "Your agent-authored summary of that tool result.",
        },
    },
    "required": ["tool_call_id", "summary"],
    "additionalProperties": False,
}

_SUMMARIZE_ITEMS_DESCRIPTION = (
    "REQUIRED, non-empty. The tool results to replace with your own compact "
    "summaries, each with 'tool_call_id' (the id of the prior tool-result "
    "block) and 'summary' (your agent-authored text). Supports multiple items "
    "per call. The original is NOT deleted — it remains retrievable from "
    "events.jsonl by tool_call_id. Pick targets from "
    "`_meta.agent_meta.agent_state.current_tool_result_chars.top_results`. "
    "This action RECORDS ONLY: the active provider context may still carry "
    "the old raw results until context(action='rebuild') applies them."
)

_REBUILD_ITEMS_DESCRIPTION = (
    "Optional — omit it entirely for the ordinary call. Every rebuild first "
    "re-reads and recomposes ALL canonical system-prompt sections from durable "
    "and configured sources, then applies summaries, then requests provider "
    "replay with the new prompt/history. context(action='rebuild', input={}) is "
    "valid even with zero pending summaries; an explicit null means the same. "
    "Pass items to record those summaries after prompt composition and apply "
    "them in the same call. Same item shape as context(action='summarize')."
)

_SUMMARIZE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "description": _SUMMARIZE_ITEMS_DESCRIPTION,
            "items": _ITEM_SCHEMA,
        },
    },
    "required": ["items"],
    "additionalProperties": False,
}

# ``items`` is genuinely OPTIONAL here — it is deliberately absent from
# ``required``, unlike every other optional field in this package.
#
# The usual LTP v2 convention is "REQUIRED but nullable", because a strict
# provider schema has no other way to express an optional field. That
# convention is wrong for this action: ``context(action='rebuild', input={})``
# is the *ordinary* call (apply the already-pending summaries), not an edge
# case, so the model-visible schema must accept a bare ``{}``. Listing ``items``
# in ``required`` would advertise a contract the handler does not have — the
# handler accepts ``{}`` — and would make the documented ordinary call
# schema-invalid.
#
# ``type`` stays ``["array", "null"]`` so an explicit ``{"items": null}`` from a
# provider that always materializes declared properties is still accepted;
# ``_strip_nulls`` turns that back into "absent" before the engine sees it. So
# ``{}`` and ``{"items": null}`` are the same ordinary pure-rebuild call, and
# both are schema-valid.
_REBUILD_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": ["array", "null"],
            "description": _REBUILD_ITEMS_DESCRIPTION,
            "items": _ITEM_SCHEMA,
        },
    },
    "required": [],
    "additionalProperties": False,
}


def _summarize_action(agent, args: dict) -> dict:
    """``context(action='summarize')`` — record only, never rebuild.

    Delegates to the shared private engine with the rebuild discriminator
    pinned off. The engine's item validation, per-item results, pending
    markers, raw-log recovery hints, partial/error behavior, and diagnostics
    are used verbatim; this wrapper only fixes which mode is requested, so the
    public action cannot silently rebuild.
    """
    return _summarize_engine(agent, {**args, "rebuild": False})


def _rebuild_action(agent, args: dict) -> dict:
    """Perform the one active full context reconstruction operation.

    Ordering is contractual: first re-read/recompose every canonical prompt
    source through Agent's shared refresh/molt path, then let the summary engine
    record/apply pending or newly supplied summaries, then request provider
    history replay. A bare input remains meaningful with zero pending summaries.
    """
    reconstruct = getattr(agent, "_reconstruct_context", None)
    if not callable(reconstruct):
        return {
            "status": "error",
            "reason": "context_reconstruction_unavailable",
            "message": "This agent does not provide the canonical context reconstruction hook.",
        }
    try:
        reconstruct()
    except Exception as exc:
        try:
            agent._log("context_reconstruction_failed", error=type(exc).__name__)
        except Exception:
            pass
        return {
            "status": "error",
            "reason": "context_reconstruction_failed",
            "message": f"Canonical prompt reconstruction failed: {type(exc).__name__}.",
        }

    result = _summarize_engine(agent, {**args, "rebuild": True})
    if isinstance(result, dict):
        result["prompt_reconstructed"] = True
        result["prompt_reconstruction"] = (
            "All canonical prompt sources were re-read and recomposed before "
            "summary processing."
        )
    return result


# The one canonical child registry: name, canonical input schema, and the
# underlying ``(agent, args)`` handler. Declaring names, order, schemas, and
# handlers in a single place is what makes schema-vs-dispatch drift
# structurally impossible — there is no second list to forget to update, so a
# child can never be schema-advertised but dispatch-rejected.
#
# Order here is the model-facing ``action`` enum order and the ``input.oneOf``
# branch order: the lifecycle operation first, then the two context-hygiene
# operations in the order they are used (record, then apply).
#
# ``manual`` is absent: ``build_manual_child`` owns that child's schema and
# handler, and :func:`_build_children` appends it last.
_CHILD_SPECS: tuple[tuple[str, dict[str, Any], Any], ...] = (
    ("molt", _MOLT_INPUT_SCHEMA, _context_molt),
    ("summarize", _SUMMARIZE_INPUT_SCHEMA, _summarize_action),
    ("rebuild", _REBUILD_INPUT_SCHEMA, _rebuild_action),
)

#: Public action order, derived from the one registry (``manual`` last).
ACTION_ORDER: tuple[str, ...] = tuple(name for name, _s, _h in _CHILD_SPECS) + ("manual",)

#: The installed intrinsic-skill directory ``manual`` reads. This is the
#: ``load_installed_manual`` skill name, not the family name.
_MANUAL_SKILL_NAME = "context-manual"

#: Envelope metadata Context owns out-of-band rather than as action input.
# ``molt`` alone consumes these values; the package-local model-facing surface
# lifts them from the closed root and threads them only to that handler.
_MOLT_ENVELOPE_KEYS = ("_tc_id", "_reasoning", "reasoning", "_initiator")


#: This family's own per-action routing prose. The generic composer writes a
#: neutral "Required operation within the context family." description; the
#: guidance the model actually needs to pick an action replaces it in
#: :func:`get_schema` rather than being lost.
_ACTION_ENUM_DESCRIPTION = (
    'Required operation. '
    'molt: shed your conversation context, keep the durable stores. Requires '
    '`summary` and a valid `session_journal_path` — tend the four stores '
    'BEFORE molting. See context-manual.\n'
    'summarize: record your own compact replacements for prior tool results in '
    'runtime history. RECORD ONLY — it does not rebuild, so the active '
    'provider context may still carry the old raw results.\n'
    'rebuild: re-read and recompose ALL canonical prompt sources, then apply '
    'pending/new summaries, then replay provider context with the new prompt and '
    'history. Bare input is valid even with zero pending summaries. Prefer one '
    'tactical rebuild; do not loop rebuild.\n'
    'manual: return the installed context-manual skill without performing any '
    'context operation.\n'
    'Your name is not here: use system(action=\'name_set\'|\'name_nickname\').'
)
_CONTEXT_DESCRIPTION = "Your context: shed it, compact it, rebuild it. One tool, four actions, each with its own strict input object: context(action=..., input={...}, reasoning='why'). molt: 凝蜕 — shed the conversation, keep the durable stores; requires a written session journal. summarize: record compact replacements for bulky prior tool results (records only, does NOT rebuild). rebuild: re-read and recompose every canonical prompt source, then apply pending/new summaries, then replay provider context with the new prompt/history; bare input is valid even with zero pending summaries. manual: return the installed context-manual skill. Your name lives on system(action='name_set'|'name_nickname'); your 灵台 and pad are lingtai(...) and pad(...). Note the two levels: the ACTION named summarize is this domain operation, while the optional ROOT summarize boolean is the unrelated result-presentation control — leave it false here (results are small), and call manual with summarize=false so the exact molt procedure is not summarized away."


# The one live package-local model-facing surface.  It owns actual schema
# composition, dispatch binding, and ManualTool adaptation; it is not an Agent
# Plugin descriptor and performs no registration or activation.  Keeping the
# action-spec getter live preserves the existing single source for the
# schema-only family and every agent-bound dispatch.
_CONTEXT_PLUGIN = ContextToolPlugin(
    root_name="context",
    action_specs=lambda: _CHILD_SPECS,
    child_diagnostics=_CHILD_DIAGNOSTICS,
    manual_skill_name=_MANUAL_SKILL_NAME,
    molt_envelope_keys=_MOLT_ENVELOPE_KEYS,
    action_enum_description=_ACTION_ENUM_DESCRIPTION,
    description=_CONTEXT_DESCRIPTION,
)

# Backward-compatible private seam for focused package tests and consumers that
# inspect the schema-only family.  Construction still occurred at import time in
# ``ContextToolPlugin`` and remains the collision check.
_FAMILY = _CONTEXT_PLUGIN.schema_family


def _build_children(agent, envelope=None):
    """Return Context's real children through its package-local surface."""
    return _CONTEXT_PLUGIN.build_children(agent, envelope)


def get_description(lang: str = "en") -> str:
    return _CONTEXT_PLUGIN.get_description(lang)


def get_schema(lang: str = "en") -> dict:
    return _CONTEXT_PLUGIN.get_schema(lang)


def handle(agent, args: dict) -> dict:
    """Dispatch Context through its package-local model-facing surface."""
    return _CONTEXT_PLUGIN.handle(agent, args)

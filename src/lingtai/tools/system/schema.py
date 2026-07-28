"""Schema data — canonical per-action input schemas and prose for ``system``.

The system tool is an LTP v2 family (``../CONTRACT.md``): the model-facing root
is the closed ``action`` + ``input`` + ``reasoning`` + ``summarize`` envelope,
and each action's arguments live in its own strict ``input`` object.

This module holds only data: each action's own canonical strict
``input_schema`` (:data:`INPUT_SCHEMAS`) and the canonical English prose.
``__init__.py`` composes these into the public model-facing schema via the
generic ``ToolFamily`` infra (``lingtai.tools.tool_family``) — see
``__init__.py::_build_children``/``get_schema``. ``lang`` is accepted on
:func:`get_description` for source compatibility and does not select localized
aliases; schema prose is canonical English, language-independent.

The migration moved the six pre-migration flat sibling fields (``reason``,
``address``, ``preset``, ``revert_preset``, ``rebuild``, ``items``) into the
``input`` object of exactly the actions that read them. Their descriptions,
types, and defaults are carried over verbatim; no action was added, removed,
renamed, or reordered, and no field changed meaning.

Two fields deserve a note because they are not a straight carry-over of the
pre-migration *schema*:

* ``sleep.force`` was always read by ``karma._sleep`` (the kernel#112 escape
  hatch) but never advertised in the flat schema. A strict child ``input``
  must declare every key its handler accepts, or dispatch would reject a call
  that succeeds today, so it is declared here. This surfaces an existing
  behavior; it does not add one.
* ``notification_threshold_chars`` is deliberately still absent. It is
  config-only (``manifest.summarize_notification_threshold`` + refresh), and
  ``summarize._summarize``'s loud runtime-mutation refusal is retained as the
  inner layer for direct in-process callers that bypass the envelope.

Optional fields are declared in the provider-compatible nullable
representation (``"type": ["string", "null"]`` plus membership in
``required``) per ``tools/CONTRACT.md`` "Envelope": strict OpenAI schemas have
no other way to express an optional field. ``__init__.py`` strips those nulls
back to *absent* before the pre-existing handlers run, so
``args.get("reason", "")``-style defaulting is preserved exactly.
"""
from __future__ import annotations

from typing import Any

from ..tool_family.manual import MANUAL_INPUT_SCHEMA

# The canonical action order. This is the single source for the schema's
# ``action`` enum order, the ``input.oneOf``/``allOf`` branch order, and the
# child registration order in ``__init__.py`` — one list, not three. The order
# is the pre-migration enum order, unchanged.
ACTION_ORDER = (
    "refresh",
    "sleep",
    "lull",
    "interrupt",
    "suspend",
    "cpr",
    "clear",
    "nirvana",
    "presets",
    "summarize",
    "manual",
)

# --- Shared field descriptions, carried over verbatim from the flat schema ---

_REASON_DESCRIPTION = (
    "Reason for sleep, refresh, or clear (logged to the event log; for clear, "
    "becomes the source tag in the recovery summary)."
)

_ADDRESS_DESCRIPTION = (
    "Target agent's address (working directory path). Required for interrupt, "
    "lull, suspend, cpr, clear, nirvana."
)

_PRESET_DESCRIPTION = (
    "Optional preset to swap to before refreshing. A preset is a {LLM, "
    "capabilities} bundle from your library. Use action='presets' to list. "
    "Swap is light and reversible. If current context exceeds target preset's "
    "context_limit, swap is refused — molt first."
)

_REVERT_PRESET_DESCRIPTION = (
    "Optional. Pass true with action='refresh' to swap back to your default "
    "preset (manifest.preset.default — typically the one your agent was "
    "created with). Cannot be used together with the 'preset' argument. "
    "Useful as a 'home button' after experimenting with another preset, "
    "without needing to remember your default's name. Errors if no default is "
    "configured."
)

_FORCE_DESCRIPTION = (
    "Optional for action='sleep'. When true, go to sleep even though unread "
    "notifications are already waiting on disk. The default (false) refuses "
    "the transition instead, so mail that arrived during this same turn is "
    "not silently slept through. Use only when you knowingly want to sleep "
    "anyway."
)

_REBUILD_DESCRIPTION = (
    "For action='summarize' (default false): request a provider-context "
    "rebuild that makes recorded summaries active in the active provider "
    "context now. With items, summaries are recorded first and then the "
    "rebuild is requested; with no items, it is a pure rebuild using the "
    "already-pending summaries. When false (the default), summarize only "
    "records compact replacements in runtime history and does NOT rebuild the "
    "active provider context — the old raw result may still ride the current "
    "continuation until a rebuild applies it (a manual rebuild=true, or the "
    "1.0 full-context hard boundary where the runtime forces a rebuild "
    "regardless of pending). Prefer one tactical rebuild=true call when "
    "context is high (>=0.85 / the context.rebuild hint) or a fresh context is "
    "worth the cache-miss cost; do not loop rebuild. Note: rebuild=false with "
    "no items is an invalid no-op."
)

_ITEMS_DESCRIPTION = (
    "Required for action='summarize' unless rebuild=true (a bare rebuild=true "
    "rebuilds already-pending summaries with no items). List of items to "
    "summarize, each with 'tool_call_id' (the id of the prior tool-result "
    "block) and 'summary' (your agent-authored summary text). Supports "
    "multiple items per call. The original result is NOT deleted — it remains "
    "retrievable from events.jsonl by tool_call_id."
)

_ITEMS_ARRAY_SCHEMA: dict[str, Any] = {
    "type": "array",
    "description": _ITEMS_DESCRIPTION,
    "items": {
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
    },
}


def _address_input_schema() -> dict[str, Any]:
    """Build the shared input shape for the six address-taking verbs.

    ``lull``/``interrupt``/``suspend``/``cpr``/``clear``/``nirvana`` take
    exactly the same two fields, so they are generated rather than restated
    six times. Each call returns a fresh dict so no two children share a
    mutable schema container.
    """
    return {
        "type": "object",
        "properties": {
            "address": {"type": "string", "description": _ADDRESS_DESCRIPTION},
            "reason": {
                "type": ["string", "null"],
                "description": _REASON_DESCRIPTION,
            },
        },
        "required": ["address", "reason"],
        "additionalProperties": False,
    }


_REFRESH_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {"type": ["string", "null"], "description": _REASON_DESCRIPTION},
        "preset": {"type": ["string", "null"], "description": _PRESET_DESCRIPTION},
        "revert_preset": {
            "type": ["boolean", "null"],
            "description": _REVERT_PRESET_DESCRIPTION,
        },
    },
    "required": ["reason", "preset", "revert_preset"],
    "additionalProperties": False,
}

_SLEEP_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "reason": {"type": ["string", "null"], "description": _REASON_DESCRIPTION},
        "force": {"type": ["boolean", "null"], "description": _FORCE_DESCRIPTION},
    },
    "required": ["reason", "force"],
    "additionalProperties": False,
}

_PRESETS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

_SUMMARIZE_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": ["array", "null"],
            "description": _ITEMS_DESCRIPTION,
            "items": _ITEMS_ARRAY_SCHEMA["items"],
        },
        "rebuild": {"type": ["boolean", "null"], "description": _REBUILD_DESCRIPTION},
    },
    "required": ["items", "rebuild"],
    "additionalProperties": False,
}

INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "refresh": _REFRESH_INPUT_SCHEMA,
    "sleep": _SLEEP_INPUT_SCHEMA,
    "lull": _address_input_schema(),
    "interrupt": _address_input_schema(),
    "suspend": _address_input_schema(),
    "cpr": _address_input_schema(),
    "clear": _address_input_schema(),
    "nirvana": _address_input_schema(),
    "presets": _PRESETS_INPUT_SCHEMA,
    "summarize": _SUMMARIZE_INPUT_SCHEMA,
    # Referenced, not restated: ``build_manual_child`` owns this literal, so
    # the schema-only family and the dispatching family cannot drift
    # (``tool_family/CONTRACT.md`` Contract rules).
    "manual": MANUAL_INPUT_SCHEMA,
}

# The per-action prose the model reads to choose an action. Carried over
# verbatim from the pre-migration flat ``action`` enum description, with the
# argument references restated in the ``input`` shape they now take.
ACTION_ENUM_DESCRIPTION = (
    "refresh: rebuild from init.json — same identity, preserved conversation. "
    "Reloads MCP, capabilities, addons, LLM, prompt sections. See "
    "system-manual.\n\n"
    "presets: list available presets with tags, connectivity, capabilities. "
    "See system-manual.\n\n"
    "sleep: go to sleep until mail wakes you. Self only.\n\n"
    "lull: put another agent to sleep (karma).\n\n"
    "suspend: freeze another agent (karma).\n\n"
    "cpr: resuscitate suspended agent (karma).\n\n"
    "interrupt: cancel another agent's turn (karma).\n\n"
    "clear: force molt on another agent (karma). See system-manual.\n\n"
    "nirvana: permanently destroy an agent (karma + nirvana). See "
    "system-manual.\n\n"
    "summarize: record an agent-authored compact replacement for one or more "
    "prior tool-result blocks in runtime history. Pass "
    "input={'items': [{'tool_call_id': ..., 'summary': ...}, ...], "
    "'rebuild': null}. The original result remains in events.jsonl; the active "
    "provider context may still contain the old raw result until a rebuild "
    "applies it (manual rebuild=true, or the runtime's forced rebuild at the "
    "1.0 full-context hard boundary). Use after digesting a large result to "
    "free context budget. Pass rebuild=true (default false) to also request a "
    "provider-context rebuild that applies the pending summaries now; "
    "rebuild=true with no items is a pure rebuild of already-pending "
    "summaries. Do not loop rebuild/summarize. Choose the tool_call_ids to "
    "compress from "
    "_meta.agent_meta.agent_state.current_tool_result_chars.top_results (the "
    "ranked list of the largest formal results in context) — large results are "
    "surfaced there, not pushed as notifications. (Legacy: if a stale "
    "large_tool_result reminder still exists in system.json, a successful "
    "summarize of its tool_call_id also clears it.) To read or dismiss "
    "notifications, use the notification tool.\n\n"
    "manual: call system(action='manual', input={}) to return the installed "
    "system-manual skill without changing runtime state."
)


def get_description(lang: str = "en") -> str:
    return (
        "Runtime inspection, lifecycle control, synchronization, and "
        "inter-agent management.\n\n"
        "Self-actions (no permissions needed): sleep, refresh, presets, "
        "summarize, manual.\n"
        "Karma actions (require admin.karma=True): lull, interrupt, suspend, "
        "cpr, clear.\n"
        "Nirvana (require admin.karma=True AND admin.nirvana=True): nirvana — "
        "this permanently destroys an agent and is irreversible.\n\n"
        "Every call takes action + input + reasoning; input is the strict "
        "argument object for the selected action. The karma verbs take "
        "input={'address': '<agent working dir>', 'reason': ...}; refresh "
        "takes input={'reason': ..., 'preset': ..., 'revert_preset': ...}; "
        "presets and manual take input={}.\n\n"
        "Notification verbs (check/dismiss) are NOT here — they live on the "
        "standalone notification tool. Call system(action='manual', input={}) "
        "to return the installed system-manual skill.\n\n"
        "Result sizes: presets and summarize can be bulky, so root "
        "summarize=true may help there when you do not need the exact entries; "
        "every other action returns a short receipt you should read exactly, so "
        "leave summarize false. Call manual with summarize=false so the exact "
        "procedure is not summarized away."
    )

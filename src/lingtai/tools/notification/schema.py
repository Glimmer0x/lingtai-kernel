"""Schema data — canonical per-action input schemas and prose for ``notification``.

The notification tool exposes ``check``, the three atomic dismiss verbs
(``dismiss_channel``, ``dismiss_event``, ``dismiss_ref``), and the strictly
read-only progressive-disclosure action ``manual``. ``summarize`` is *not* a
notification verb — it remains a ``system`` action; the root ``summarize``
boolean is the cross-cutting LTP v2 result-post-processing control, not an
action.

This module holds only data: each action's own canonical strict
``input_schema`` (:data:`INPUT_SCHEMAS`) and the canonical English prose.
``__init__.py`` composes these into the public model-facing schema via the
generic ``ToolFamily`` infra (``lingtai.tools.tool_family``) — see
``__init__.py::_schema_only_family``/``get_schema``. ``lang`` is accepted on
:func:`get_description` and :func:`get_schema` for source compatibility and
does not select localized aliases; schema prose is canonical English,
language-independent.

Optional dismiss fields are declared in the provider-compatible nullable
representation (``"type": ["string", "null"]`` plus membership in
``required``) per ``tools/CONTRACT.md`` "Envelope": strict OpenAI schemas
have no other way to express an optional field. ``__init__.py`` strips those
nulls back to *absent* before the pre-existing dismiss handlers run, so
``args.get("channel", "system")``-style defaulting is preserved exactly.
"""
from __future__ import annotations

from typing import Any

LARGE_RESULT_DISMISS_ACTION_NOTE = (
    "Legacy: the kernel no longer raises large_tool_result reminders — large "
    "results are ranked under _meta.agent_meta.agent_state.current_tool_result_chars and "
    "compacted via system(action=summarize). Any large_tool_result event still "
    "present (e.g. persisted before this change or pre-molt) can be dismissed "
    "as an escape hatch. Dismissal only clears the notification surface; the "
    "original result stays in chat history and events.jsonl. See "
    "notification-manual."
)

LARGE_RESULT_FORCE_NOTE = (
    "Does not affect large_tool_result reminder dismissal; that escape hatch "
    "is always allowed and clears only the reminder surface."
)

# The canonical action order. This is the single source for the schema's
# ``action`` enum order, the ``input.oneOf``/``allOf`` branch order, and the
# child registration order in ``__init__.py`` — one list, not three.
ACTION_ORDER = ("check", "dismiss_channel", "dismiss_event", "dismiss_ref", "manual")

_CHANNEL_DESCRIPTION = (
    "Notification channel to act on (e.g. soul, system, mcp.telegram). "
    "Required for dismiss_channel; for dismiss_event/dismiss_ref it defaults "
    "to 'system'. For producer-owned channels like email, prefer the "
    "producer's own verb (email(read/dismiss))."
)

_FORCE_DESCRIPTION = (
    "Optional for dismiss verbs. When true, bypasses a producer-registered "
    "generic-dismiss guard and the stale-channel-version refusal. Use only "
    "when knowingly clearing a stale mirror; producer-owned state is never "
    "changed. " + LARGE_RESULT_FORCE_NOTE
)

_REASON_DESCRIPTION = (
    "Optional acknowledgement reason, logged to the event log. Required when "
    "dismissing the post-molt continuation channel (use "
    "reason='<continue|defer|obsolete>: ...')."
)

_CHECK_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}

_DISMISS_CHANNEL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "channel": {"type": "string", "description": _CHANNEL_DESCRIPTION},
        "force": {"type": ["boolean", "null"], "description": _FORCE_DESCRIPTION},
        "reason": {"type": ["string", "null"], "description": _REASON_DESCRIPTION},
    },
    "required": ["channel", "force", "reason"],
    "additionalProperties": False,
}

_DISMISS_EVENT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "event_id": {
            "type": "string",
            "description": (
                "Remove only the matching system notification event_id from "
                ".notification/system.json instead of the whole channel."
            ),
        },
        "channel": {"type": ["string", "null"], "description": _CHANNEL_DESCRIPTION},
        "force": {"type": ["boolean", "null"], "description": _FORCE_DESCRIPTION},
        "reason": {"type": ["string", "null"], "description": _REASON_DESCRIPTION},
    },
    "required": ["event_id", "channel", "force", "reason"],
    "additionalProperties": False,
}

_DISMISS_REF_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "ref_id": {
            "type": "string",
            "description": (
                "Remove system notification event(s) carrying this producer "
                "ref_id from .notification/system.json instead of the whole "
                "channel."
            ),
        },
        "channel": {"type": ["string", "null"], "description": _CHANNEL_DESCRIPTION},
        "force": {"type": ["boolean", "null"], "description": _FORCE_DESCRIPTION},
        "reason": {"type": ["string", "null"], "description": _REASON_DESCRIPTION},
    },
    "required": ["ref_id", "channel", "force", "reason"],
    "additionalProperties": False,
}

# Declared verbatim as ``tool_family.manual.build_manual_child`` declares it,
# so the schema-only family composed here and the real dispatching family in
# ``__init__.py`` (which registers the shared ManualTool child, not this dict)
# advertise byte-identical ``manual`` input. ``test_notification_tool.py``
# pins that equality so the two cannot drift.
_MANUAL_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

INPUT_SCHEMAS: dict[str, dict[str, Any]] = {
    "check": _CHECK_INPUT_SCHEMA,
    "dismiss_channel": _DISMISS_CHANNEL_INPUT_SCHEMA,
    "dismiss_event": _DISMISS_EVENT_INPUT_SCHEMA,
    "dismiss_ref": _DISMISS_REF_INPUT_SCHEMA,
    "manual": _MANUAL_INPUT_SCHEMA,
}

ACTION_ENUM_DESCRIPTION = (
    "check: read all notification channels. Returns a placeholder; the live "
    "payload is stamped onto this same result under "
    "`_meta.agent_meta.notifications.attention` and `_meta.agent_meta.guidance.transient`. "
    "Replace-only — do not call voluntarily after handling; dismiss instead. "
    "Prefer coalescing the dismiss with other tool work you already need this "
    "turn when safe; dismiss alone only when there is no useful coalesced "
    "work or safety requires it.\n\n"
    "dismiss_channel: clear one notification channel whole "
    "(input={'channel': '<name>', ...}). Use producer-specific verbs first "
    "(for email, use email(read/dismiss)); guarded channels require "
    "force=true only for stale mirrors. Does not accept event_id/ref_id — "
    "use dismiss_event/dismiss_ref for those.\n\n"
    "dismiss_event: remove a single system event by event_id from "
    ".notification/system.json (channel defaults to 'system' when null).\n\n"
    "dismiss_ref: remove system event(s) by ref_id from "
    ".notification/system.json (channel defaults to 'system' when null).\n\n"
    "manual: call notification(action='manual', input={}) to return the "
    "installed notification-manual skill body. This action is strictly "
    "read-only and does not read or change notification state."
) + "\n\n" + LARGE_RESULT_DISMISS_ACTION_NOTE


def get_description(lang: str = "en") -> str:
    return "Notification surface — read and clear the agent's notification channels. Self-actions, no permissions needed.\n\nThis is the only tool that exposes notification verbs; the system tool no longer offers notification or dismiss aliases.\n\nEvery call takes action + input + reasoning; input is the strict argument object for the selected action. Use notification(action='check', input={}, reasoning='...') to read all channels, notification(action='dismiss_channel', input={'channel': '<name>', 'force': null, 'reason': null}, reasoning='...') to clear one channel whole, and dismiss_event / dismiss_ref to remove a single system event by event_id / ref_id. Use notification(action='manual', input={}, reasoning='...') to return the installed notification manual; this action is strictly read-only and does not change notification state. To compress a large tool result, use system(action=summarize)."


# NOTE: ``get_schema`` is deliberately NOT defined here. The model-facing
# schema is *composed* from the data above by the generic ``ToolFamily``
# infra, and that composition lives next to the child registry it is
# generated from — ``__init__.py::get_schema``. Defining a second one here
# would either duplicate the composition or import the package back into its
# own data module. ``__init__.py`` re-exports the composed ``get_schema``, so
# ``lingtai.tools.notification.get_schema`` (the intrinsic protocol entry
# point ``_build_tool_schemas`` actually calls) is unchanged.

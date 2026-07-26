"""Schema and description for the standalone ``notification`` intrinsic."""
from __future__ import annotations

from typing import Any


LARGE_RESULT_DISMISS_ACTION_NOTE = (
    "Legacy: the kernel no longer raises large_tool_result reminders — large "
    "results are ranked under _meta.agent_meta.agent_state.current_tool_result_chars and "
    "compacted via system(action=summarize). Any large_tool_result event still "
    "present (for example, persisted before this change or pre-molt) can be "
    "dismissed as an escape hatch. Dismissal only clears the notification "
    "surface; the original result stays in chat history and events.jsonl. See "
    "notification-manual."
)

LARGE_RESULT_FORCE_NOTE = (
    "Does not affect large_tool_result reminder dismissal; that escape hatch "
    "is always allowed and clears only the reminder surface."
)


def _input_branch(
    title: str,
    properties: dict[str, dict[str, Any]],
    required: list[str],
) -> dict[str, Any]:
    return {
        "title": title,
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def get_description(lang: str = "en") -> str:
    return (
        "Notification surface — read and clear the agent's notification channels. "
        "The public call is always notification(action=..., input={...}); "
        "BaseAgent alone adds optional root reasoning, never nested input. "
        "Self-actions need no permissions. This is the only tool that exposes "
        "notification verbs; system has no notification or dismiss alias. Use "
        "notification(action='check', input={}) to read all channels, "
        "notification(action='dismiss_channel', input={'channel': '...'}) to "
        "clear one channel whole, and the event/ref actions to remove a single "
        "system event. Use notification(action='manual', input={}) to return the "
        "installed notification manual; manual is strictly read-only. To compress "
        "a large tool result, use system(action='summarize')."
    )


def get_schema(lang: str = "en") -> dict[str, Any]:
    """Return the raw closed action/input schema.

    ``reasoning`` is deliberately absent: BaseAgent injects it as optional root
    metadata while constructing the Agent-facing FunctionSchema. Each nested
    branch is closed and owns only the fields for its action.
    """
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "check",
                    "dismiss_channel",
                    "dismiss_event",
                    "dismiss_ref",
                    "manual",
                ],
                "description": (
                    "Required operation: check, dismiss_channel, dismiss_event, "
                    "dismiss_ref, or manual.\n\n"
                    "check reads all notification channels. dismiss_channel clears "
                    "one whole channel and rejects event_id/ref_id; dismiss_event "
                    "removes one system event by event_id; dismiss_ref removes "
                    "system events by ref_id; manual reads the installed manual "
                    "without notification-state changes.\n\n"
                    + LARGE_RESULT_DISMISS_ACTION_NOTE
                ),
            },
            "input": {
                "description": (
                    "Strict action-specific notification input; no nested "
                    "reasoning field."
                ),
                "anyOf": [
                    # Keep separate empty branches for check and manual. This is
                    # the established action/input precedent; no fabricated
                    # discriminator is needed for their distinct action values.
                    _input_branch("check input", {}, []),
                    _input_branch(
                        "dismiss_channel input",
                        {
                            "channel": {
                                "type": "string",
                                "description": "Notification channel to clear whole.",
                            },
                            "force": {
                                "type": "boolean",
                                "description": (
                                    "When true, bypass a producer guard or stale "
                                    "mirror refusal; producer state is never changed. "
                                    + LARGE_RESULT_FORCE_NOTE
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": (
                                    "Acknowledgement reason; required for post-molt "
                                    "continuation dismissal."
                                ),
                            },
                        },
                        ["channel"],
                    ),
                    _input_branch(
                        "dismiss_event input",
                        {
                            "event_id": {
                                "type": "string",
                                "description": "System event_id to remove.",
                            },
                            "channel": {
                                "type": "string",
                                "description": "Target channel; defaults to system.",
                            },
                            "force": {
                                "type": "boolean",
                                "description": (
                                    "When true, bypass a stale mirror refusal; "
                                    "producer state is never changed. "
                                    + LARGE_RESULT_FORCE_NOTE
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": "Optional acknowledgement reason.",
                            },
                        },
                        ["event_id"],
                    ),
                    _input_branch(
                        "dismiss_ref input",
                        {
                            "ref_id": {
                                "type": "string",
                                "description": "Producer ref_id whose system events are removed.",
                            },
                            "channel": {
                                "type": "string",
                                "description": "Target channel; defaults to system.",
                            },
                            "force": {
                                "type": "boolean",
                                "description": (
                                    "When true, bypass a stale mirror refusal; "
                                    "producer state is never changed. "
                                    + LARGE_RESULT_FORCE_NOTE
                                ),
                            },
                            "reason": {
                                "type": "string",
                                "description": "Optional acknowledgement reason.",
                            },
                        },
                        ["ref_id"],
                    ),
                    _input_branch("manual input", {}, []),
                ],
            },
        },
        "required": ["action", "input"],
        "additionalProperties": False,
    }

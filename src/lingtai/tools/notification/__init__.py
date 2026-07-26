"""Notification intrinsic — the standalone notification surface.

The public boundary is a closed root ``action`` plus required nested ``input``.
The raw schema owns no ``reasoning`` field; BaseAgent alone injects optional root
reasoning into the Agent-facing schema. The five actions are:

* ``check`` — read the live notification surface through the kernel's
  post-hook placeholder;
* ``dismiss_channel`` — clear one notification mirror whole;
* ``dismiss_event`` — remove one system event by event_id;
* ``dismiss_ref`` — remove system event(s) by ref_id;
* ``manual`` — read the initialized notification-manual resource.

Dismissal remains delegated to the canonical notification Core helper. This
module owns only strict envelope validation, dispatch, the check placeholder,
and installed-manual retrieval.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .._settings import SettingsSnapshot, current_setting, read_settings

# Schema (tool registration).
from .schema import get_description, get_schema  # noqa: F401

# Single-source delegate — the canonical dismissal helper. No notification
# policy is reimplemented here.
from lingtai.kernel.notifications import dismiss_channel


_ACTION_FIELDS: dict[str, tuple[str, ...]] = {
    "check": (),
    "dismiss_channel": ("channel", "force", "reason"),
    "dismiss_event": ("event_id", "channel", "force", "reason"),
    "dismiss_ref": ("ref_id", "channel", "force", "reason"),
    "manual": (),
}

# ``_tc_id`` is injected by intrinsic dispatch. ``reasoning`` and ``_reasoning``
# are Agent/executor metadata accepted only at this internal boundary. None of
# these are public raw-schema properties.
_ALLOWED_ROOT_FIELDS = ("action", "input", "reasoning", "_reasoning", "_tc_id")

_CHECK_PLACEHOLDER_MESSAGE = (
    "Voluntary notification(action='check', input={}) read. The live notification payload "
    "is delivered via the kernel meta-block under the `_meta.agent_meta.notifications.attention` and "
    "`_meta.agent_meta.guidance.transient` keys on this same result. If those keys are "
    "absent, no notifications are active."
)


def _check(agent, args: dict) -> dict:
    """Voluntary read of the notification surface — returns a placeholder."""
    return {
        "_notification_placeholder": True,
        "message": _CHECK_PLACEHOLDER_MESSAGE,
    }


def _manual(agent, args: dict) -> dict:
    """Read only the initialized notification manual resource."""
    manual_path = (
        agent._working_dir
        / ".library"
        / "intrinsic"
        / "capabilities"
        / "notification-manual"
        / "SKILL.md"
    )
    if not manual_path.is_file():
        return {
            "status": "degraded",
            "notification_manual": "",
            "manual_path": str(manual_path),
            "error": (
                "notification manual missing — initializer may have failed or "
                "capability not installed correctly"
            ),
        }
    return {
        "status": "ok",
        "notification_manual": manual_path.read_text(encoding="utf-8"),
        "manual_path": str(manual_path),
    }


def _dismiss_channel(agent, args: dict) -> dict:
    """Clear one notification channel whole."""
    channel = args.get("channel")
    if channel is None:
        agent._log("notification_dismiss_missing_channel")
        return {
            "status": "error",
            "reason": "missing_channel",
            "message": (
                "notification(action='dismiss_channel', input={'channel': '<name>'}) "
                "requires input.channel."
            ),
        }
    return dismiss_channel(
        agent,
        channel,
        invoked_by="notification",
        force=bool(args.get("force", False)),
        reason=args.get("reason"),
    )


def _dismiss_event(agent, args: dict) -> dict:
    """Remove a single ``system`` event by ``event_id``."""
    event_id = args.get("event_id")
    if not event_id:
        agent._log("notification_dismiss_missing_event_id")
        return {
            "status": "error",
            "reason": "missing_event_id",
            "message": (
                "notification(action='dismiss_event', input={'event_id': '<id>'}) "
                "requires input.event_id."
            ),
        }
    return dismiss_channel(
        agent,
        args.get("channel", "system"),
        invoked_by="notification",
        force=bool(args.get("force", False)),
        reason=args.get("reason"),
        event_id=event_id,
    )


def _dismiss_ref(agent, args: dict) -> dict:
    """Remove ``system`` event(s) by ``ref_id``."""
    ref_id = args.get("ref_id")
    if not ref_id:
        agent._log("notification_dismiss_missing_ref_id")
        return {
            "status": "error",
            "reason": "missing_ref_id",
            "message": (
                "notification(action='dismiss_ref', input={'ref_id': '<id>'}) "
                "requires input.ref_id."
            ),
        }
    return dismiss_channel(
        agent,
        args.get("channel", "system"),
        invoked_by="notification",
        force=bool(args.get("force", False)),
        reason=args.get("reason"),
        ref_id=ref_id,
    )


def _mapping_keys(value: Mapping) -> tuple[list[Any], str | None]:
    """Read mapping keys without hashing untrusted or odd mapping keys."""
    try:
        keys = list(value.keys())
    except Exception:
        return [], "mapping keys could not be read"
    if any(not isinstance(key, str) for key in keys):
        return keys, "mapping keys must be strings"
    return keys, None


def _setting_diagnostic(agent) -> dict[str, Any]:
    """Reread settings and keep an unexpected reader failure bounded."""
    try:
        snapshot = read_settings(agent, "notification")
    except Exception:
        snapshot = SettingsSnapshot(
            "settings_error", "error", None, "settings file could not be read"
        )
    return current_setting(snapshot, "notification")


def _with_setting(result: Any, diagnostic: dict[str, Any]) -> dict[str, Any]:
    """Attach fresh, secret-free settings evidence to every public result."""
    if isinstance(result, Mapping):
        value = dict(result)
    else:
        value = {
            "status": "error",
            "reason": "notification_action_failed",
            "message": "notification action failed",
        }
    # Core's low-level clear error historically carried the exception text. Keep
    # its stable reason but do not expose filesystem/service details to the agent.
    if value.get("reason") == "clear_failed":
        value["message"] = "notification mirror operation failed"
    value["current_setting"] = dict(diagnostic)
    return value


def _error(message: str, diagnostic: dict[str, Any]) -> dict[str, Any]:
    return _with_setting({"status": "error", "message": message}, diagnostic)


def _validate_input_types(action: str, action_input: dict[str, Any]) -> str | None:
    """Validate value types before any notification Core/Store seam."""
    string_fields = {"channel", "event_id", "ref_id", "reason"}
    for field in string_fields:
        if field in action_input and type(action_input[field]) is not str:
            return f"notification input field {field!r} must be a string"
    if "force" in action_input and type(action_input["force"]) is not bool:
        return "notification input field 'force' must be a boolean"
    # Missing target fields retain the existing action-specific envelopes in
    # _dismiss_channel/_dismiss_event/_dismiss_ref; only wrong value types are
    # rejected at this pre-seam boundary.
    return None


def handle(agent, args: Any) -> dict:
    """Validate and dispatch one canonical notification action.

    Envelope and value validation deliberately precede every notification
    read/write/dismiss seam. Settings evidence is reread for every outcome,
    including malformed, manual, and service-error paths.
    """
    diagnostic = _setting_diagnostic(agent)

    if not isinstance(args, Mapping):
        return _error("notification arguments must be an object", diagnostic)
    root_keys, root_error = _mapping_keys(args)
    if root_error:
        return _error(f"notification {root_error}", diagnostic)
    try:
        if any(key not in _ALLOWED_ROOT_FIELDS for key in root_keys):
            return _error(
                "notification accepts only root action, input, and Agent reasoning metadata",
                diagnostic,
            )
        if "action" not in root_keys or "input" not in root_keys:
            return _error("notification requires root action and input", diagnostic)
        action = args["action"]
        raw_input = args["input"]
    except Exception:
        return _error("notification arguments are malformed", diagnostic)

    if type(action) is not str or action not in _ACTION_FIELDS:
        return _error("Unknown notification action", diagnostic)
    if not isinstance(raw_input, Mapping):
        return _error("notification input must be an object", diagnostic)
    nested_keys, nested_error = _mapping_keys(raw_input)
    if nested_error:
        return _error(f"notification input {nested_error}", diagnostic)
    try:
        action_input = dict(raw_input)
    except Exception:
        return _error("notification input must be an object", diagnostic)
    allowed_fields = _ACTION_FIELDS[action]
    try:
        if action == "dismiss_channel" and any(
            key in ("event_id", "ref_id") for key in nested_keys
        ):
            channel = action_input.get("channel")
            return _with_setting(
                {
                    "status": "error",
                    "reason": "channel_dismiss_rejects_event_target",
                    "channel": channel,
                    "message": (
                        "dismiss_channel clears a whole channel; use dismiss_event "
                        "(event_id=...) or dismiss_ref (ref_id=...) for a single "
                        "system event."
                    ),
                },
                diagnostic,
            )
        if any(key not in allowed_fields for key in nested_keys):
            return _error(
                f"unsupported notification input field for action {action!r}",
                diagnostic,
            )
    except Exception:
        return _error("notification input is malformed", diagnostic)
    if action in ("check", "manual") and action_input:
        return _error(f"{action} input must be an empty object", diagnostic)
    type_error = _validate_input_types(action, action_input)
    if type_error:
        return _error(type_error, diagnostic)

    try:
        reasoning = args.get("_reasoning")
        if reasoning is None:
            reasoning = args.get("reasoning")
    except Exception:
        reasoning = None
    if reasoning is not None and not isinstance(reasoning, str):
        return _error("notification reasoning metadata must be a string", diagnostic)

    dispatch_args = {"action": action, **action_input}
    handlers = {
        "check": _check,
        "dismiss_channel": _dismiss_channel,
        "dismiss_event": _dismiss_event,
        "dismiss_ref": _dismiss_ref,
        "manual": _manual,
    }
    try:
        result = handlers[action](agent, dispatch_args)
    except Exception:
        result = {
            "status": "error",
            "reason": "notification_action_failed",
            "message": "notification action failed",
        }
    return _with_setting(result, diagnostic)

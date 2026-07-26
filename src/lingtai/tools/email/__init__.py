"""The canonical public ``email`` intrinsic and filesystem mailbox owner.

The public boundary is a required root ``action`` plus a required closed nested
``input`` object.  The manager and mailbox primitives retain the established
internal flat calls only behind this validated dispatcher; they are not public
compatibility aliases.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lingtai.kernel.notifications import register_generic_dismiss_guard
from .._manual import load_installed_manual
from .._settings import SettingsSnapshot, current_setting, read_settings

register_generic_dismiss_guard(
    "email",
    "email(action='dismiss', input={'email_id': [...]}) or email(action='read', input={'email_id': [...]})",
)

# --- Re-exports from sub-modules for implementation/backward import users ---
from .primitives import (  # noqa: F401
    _coerce_address_list,
    _email_time,
    _inbox_dir,
    _is_self_send,
    _list_inbox,
    _load_message,
    _mailbox_dir,
    _mailman,
    _mark_read,
    _message_summary,
    _move_to_sent,
    _new_mailbox_id,
    _outbox_dir,
    _persist_to_inbox,
    _persist_to_outbox,
    _preview,
    _read_ids,
    _read_ids_path,
    _render_unread_digest,
    _rerender_unread_digest,
    _save_read_ids,
    _sent_dir,
    _summary_to_list,
    _unread_notification_context,
    mode_field,
)
from .schema import get_description, get_schema  # noqa: F401
from .manager import EmailManager  # noqa: F401


_ACTION_FIELDS: dict[str, frozenset[str]] = {
    "send": frozenset({"address", "cc", "bcc", "attachments", "subject", "message", "delay", "mode", "type"}),
    "check": frozenset({"n", "folder", "filter"}),
    "read": frozenset({"email_id", "folder"}),
    "dismiss": frozenset({"email_id"}),
    "reply": frozenset({"email_id", "message", "subject", "cc", "bcc"}),
    "reply_all": frozenset({"email_id", "message", "subject", "cc", "bcc"}),
    "search": frozenset({"query", "folder"}),
    "archive": frozenset({"email_id"}),
    "delete": frozenset({"email_id", "folder"}),
    "contacts": frozenset(),
    "add_contact": frozenset({"address", "name", "note"}),
    "remove_contact": frozenset({"address"}),
    "edit_contact": frozenset({"address", "name", "note"}),
    "manual": frozenset(),
}

# ``reasoning`` is injected and removed by BaseAgent/ToolExecutor. ``_tc_id``
# is injected by intrinsic dispatch. Neither is public email action input.
_ALLOWED_ROOT_FIELDS = frozenset({"action", "input", "reasoning", "_reasoning", "_tc_id"})
_FILTER_FIELDS = frozenset({
    "sort", "from", "subject", "contains", "after", "before", "unread_only",
    "has_attachments", "truncate",
})


def boot(agent) -> None:
    """Boot-time hook: bind one manager to the Agent."""
    agent._email_manager = EmailManager(agent)
    agent._mailbox_name = "email box"
    agent._mailbox_tool = "email"


def _mapping_keys(value: Mapping) -> tuple[list[Any], str | None]:
    """Read keys without hashing untrusted/custom mapping keys."""
    try:
        keys = list(value.keys())
    except Exception:
        return [], "mapping keys could not be read"
    if any(not isinstance(key, str) for key in keys):
        return keys, "mapping keys must be strings"
    return keys, None


def _setting_diagnostic(agent) -> dict[str, Any]:
    """Reread the Agent-owned no-op settings snapshot for every call."""
    try:
        snapshot = read_settings(agent, "email")
    except Exception:
        snapshot = SettingsSnapshot(
            "settings_error", "error", None, "settings file could not be read"
        )
    return current_setting(snapshot, "email")


def _with_setting(result: Any, diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    """Attach a fresh bounded settings snapshot to every public result."""
    if isinstance(result, Mapping):
        value = dict(result)
    else:
        value = {"status": "error", "error": "email action failed"}
    value["current_setting"] = dict(diagnostic)
    return value


def _error(message: str, diagnostic: Mapping[str, Any]) -> dict[str, Any]:
    return _with_setting({"error": message}, diagnostic)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _address_or_list(value: Any) -> bool:
    return isinstance(value, str) or _string_list(value)


def _ids(value: Any) -> bool:
    return isinstance(value, str) or _string_list(value)


def _validate_filter(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(value, Mapping):
        return None, "filter must be an object"
    keys, key_error = _mapping_keys(value)
    if key_error:
        return None, f"filter {key_error}"
    unknown = [key for key in keys if key not in _FILTER_FIELDS]
    if unknown:
        return None, "unsupported check filter field"
    try:
        result = dict(value)
    except Exception:
        return None, "filter must be an object"
    if "sort" in result and result["sort"] not in ("newest", "oldest"):
        return None, "filter sort must be newest or oldest"
    for field in ("from", "subject", "contains", "after", "before"):
        if field in result and not isinstance(result[field], str):
            return None, f"filter {field} must be a string"
    for field in ("unread_only", "has_attachments"):
        if field in result and type(result[field]) is not bool:
            return None, f"filter {field} must be a boolean"
    if "truncate" in result and type(result["truncate"]) is not int:
        return None, "filter truncate must be an integer"
    return result, None


def _validate_input(action: Any, raw_input: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Validate canonical action input before entering any mailbox seam."""
    if type(action) is not str or action not in _ACTION_FIELDS:
        return None, "action must be one of: " + ", ".join(_ACTION_FIELDS)
    if not isinstance(raw_input, Mapping):
        return None, "input is required and must be an object"
    keys, key_error = _mapping_keys(raw_input)
    if key_error:
        return None, f"email input {key_error}"
    unknown = [key for key in keys if key not in _ACTION_FIELDS[action]]
    if unknown:
        return None, f"unsupported {action} input field"
    try:
        value = dict(raw_input)
    except Exception:
        return None, "input must be an object"

    if action == "manual" or action == "contacts":
        return (value, None) if not value else (None, f"{action} input must be an empty object")
    if action in {"read", "dismiss", "reply", "reply_all", "archive", "delete"}:
        if "email_id" not in value:
            return None, "email_id is required" if action not in {"reply", "reply_all"} else f"email_id is required for {action}"
        if not _ids(value["email_id"]):
            return None, "email_id must be a string or an array of strings"
    if action in {"read", "delete"} and "folder" in value:
        allowed = ("inbox", "sent", "archive") if action == "read" else ("inbox", "archive")
        if value["folder"] not in allowed:
            return None, f"folder must be one of: {', '.join(allowed)}"
    if action in {"reply", "reply_all"}:
        if "message" not in value:
            return None, f"message is required for {action}"
        if not isinstance(value["message"], str):
            return None, "message must be a string"
        for field in ("subject",):
            if field in value and not isinstance(value[field], str):
                return None, f"{field} must be a string"
        for field in ("cc", "bcc"):
            if field in value and not _string_list(value[field]):
                return None, f"{field} must be an array of strings"
    if action == "send":
        for field in ("address", "message"):
            if field not in value:
                return None, f"{field} is required"
        if not _address_or_list(value["address"]):
            return None, "address must be a string or an array of strings"
        for field in ("subject", "message"):
            if field in value and not isinstance(value[field], str):
                return None, f"{field} must be a string"
        for field in ("cc", "bcc", "attachments"):
            if field in value and not _string_list(value[field]):
                return None, f"{field} must be an array of strings"
        if "delay" in value and type(value["delay"]) is not int:
            return None, "delay must be an integer"
        if "mode" in value and value["mode"] not in ("peer", "abs"):
            return None, "mode must be peer or abs"
        if "type" in value and value["type"] != "normal":
            return None, "type must be normal"
    if action == "check":
        if "n" in value and type(value["n"]) is not int:
            return None, "n must be an integer"
        if "folder" in value and value["folder"] not in ("inbox", "sent", "archive"):
            return None, "folder must be one of: inbox, sent, archive"
        if "filter" in value:
            checked, error = _validate_filter(value["filter"])
            if error:
                return None, error
            value["filter"] = checked
    if action == "search":
        if "query" not in value:
            return None, "query is required for search"
        if not isinstance(value["query"], str):
            return None, "query must be a string"
        if "folder" in value and value["folder"] not in ("inbox", "sent", "archive"):
            return None, "folder must be one of: inbox, sent, archive"
    if action in {"add_contact", "remove_contact", "edit_contact"}:
        if "address" not in value:
            return None, "address is required"
        if not isinstance(value["address"], str):
            return None, "address must be a string"
    if action == "add_contact":
        if "name" not in value:
            return None, "name is required"
        if not isinstance(value["name"], str):
            return None, "name must be a string"
        if "note" in value and not isinstance(value["note"], str):
            return None, "note must be a string"
    if action == "edit_contact":
        for field in ("name", "note"):
            if field in value and not isinstance(value[field], str):
                return None, f"{field} must be a string"
    return value, None


def handle(agent, args: Any) -> dict:
    """Validate, dispatch, and stamp one canonical public email call."""
    diagnostic = _setting_diagnostic(agent)
    if not isinstance(args, Mapping):
        return _error("email arguments must be an object", diagnostic)
    root_keys, key_error = _mapping_keys(args)
    if key_error:
        return _error(f"email {key_error}", diagnostic)
    if any(key not in _ALLOWED_ROOT_FIELDS for key in root_keys):
        return _error("email accepts only root action, input, and Agent reasoning metadata", diagnostic)
    if "action" not in root_keys or "input" not in root_keys:
        return _error("email requires root action and input", diagnostic)
    try:
        action = args["action"]
        raw_input = args["input"]
    except Exception:
        return _error("email arguments are malformed", diagnostic)
    for metadata_key in ("reasoning", "_reasoning"):
        if metadata_key not in root_keys:
            continue
        try:
            metadata_value = args[metadata_key]
        except Exception:
            return _error("email arguments are malformed", diagnostic)
        if not isinstance(metadata_value, str):
            return _error(f"email {metadata_key} must be a string", diagnostic)
    action_input, error = _validate_input(action, raw_input)
    if error:
        return _error(error, diagnostic)
    if action == "manual":
        return _with_setting(load_installed_manual(agent, "email"), diagnostic)
    manager = getattr(agent, "_email_manager", None)
    if manager is None:
        return _error("Internal: email manager not initialized. boot() was not called.", diagnostic)
    try:
        result = manager.handle({"action": action, **(action_input or {})})
    except Exception:
        # Preserve the established action result contract without exposing
        # filesystem, contact, or transport details from an unexpected seam.
        result = {"error": "email action failed"}
    return _with_setting(result, diagnostic)

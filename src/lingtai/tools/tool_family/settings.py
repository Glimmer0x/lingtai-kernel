"""Read-only settings discovery for an explicitly opted-in ToolFamily."""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = ["SettingRow", "SettingsProvider"]

MAX_SETTINGS_RESPONSE_BYTES = 65_536
REDACTED_VALUE = "<redacted>"
_MAX_TEXT_CHARACTERS = 1_024
_SETTINGS_ACTION = "settings"
_SETTINGS_SCHEMA = {
    "type": "object",
    "properties": {},
    "required": [],
    "additionalProperties": False,
}
_PROVIDER_FAILURE = {
    "status": "failed",
    "error_code": "SETTINGS_UNAVAILABLE",
    "message": "settings inventory is unavailable",
}
_OVERSIZE_FAILURE = {
    "status": "failed",
    "error_code": "SETTINGS_RESPONSE_TOO_LARGE",
    "message": "settings inventory exceeds the 65536-byte response limit",
    "max_bytes": MAX_SETTINGS_RESPONSE_BYTES,
}


@dataclass(frozen=True, slots=True)
class SettingRow:
    """One provider-owned row projected by the SHOW-only settings action."""

    key: str
    current: Any = field(repr=False)
    default: Any = field(repr=False)
    configurable: bool
    comment: str
    _sensitive: bool = field(default=False, repr=False)


class SettingsProvider(Protocol):
    """Return a fresh iterable of display rows without changing settings."""

    def __call__(self) -> Iterable[SettingRow]: ...


def _text(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_TEXT_CHARACTERS
    ):
        raise ValueError("invalid settings row text")
    value.encode("utf-8")
    return value


def _project(row: SettingRow) -> dict[str, Any]:
    if type(row) is not SettingRow:
        raise ValueError("provider returned a malformed settings row")
    key = _text(row.key)
    comment = _text(row.comment)
    if type(row.configurable) is not bool or type(row._sensitive) is not bool:
        raise ValueError("settings row flags must be boolean")
    current = REDACTED_VALUE if row._sensitive else row.current
    default = REDACTED_VALUE if row._sensitive else row.default
    return {
        "key": key,
        "current": current,
        "default": default,
        "configurable": row.configurable,
        "comment": comment,
    }


def _json_size(value: Mapping[str, Any], limit: int) -> int | None:
    encoder = json.JSONEncoder(
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    size = 0
    for chunk in encoder.iterencode(value):
        size += len(chunk.encode("utf-8"))
        if size > limit:
            return None
    return size


def _inventory(provider: SettingsProvider) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    size = len(b'{"settings":[') + len(b']}')
    try:
        supplied = provider()
        for item in supplied:
            projected = _project(item)
            separator_size = 1 if rows else 0
            row_size = _json_size(
                projected,
                MAX_SETTINGS_RESPONSE_BYTES - size - separator_size,
            )
            if row_size is None:
                return dict(_OVERSIZE_FAILURE)
            rows.append(projected)
            size += separator_size + row_size
    except Exception:
        return dict(_PROVIDER_FAILURE)
    return {"settings": rows}


def build_settings_child(provider: SettingsProvider) -> Any:
    """Build the reserved child without introducing a second registry."""
    if not callable(provider):
        raise ValueError("settings provider must be callable")
    from . import ChildTool

    def show(action_input: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(action_input, Mapping) or action_input:
            return {
                "status": "failed",
                "error_code": "INVALID_INPUT",
                "message": "settings accepts only the empty input object",
            }
        return _inventory(provider)

    return ChildTool(
        _SETTINGS_ACTION,
        dict(_SETTINGS_SCHEMA),
        show,
        title="settings inventory input",
    )

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
_MISSING = object()
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
    configurable: bool
    manual_ref: str
    effective: Any = field(default=_MISSING, repr=False)
    source: str | None = None
    unavailable: str | None = None
    default: Any = field(default=_MISSING, repr=False)
    config_key: str | None = None
    application_timing: str | None = None
    sensitive: bool = False


class SettingsProvider(Protocol):
    """Return a fresh iterable of display rows without changing settings."""

    def __call__(self) -> Iterable[SettingRow]: ...


def _text(value: Any, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
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
    manual_ref = _text(row.manual_ref)
    config_key = _text(row.config_key, optional=True)
    if type(row.configurable) is not bool or type(row.sensitive) is not bool:
        raise ValueError("settings row flags must be boolean")
    timing = _text(row.application_timing, optional=True)
    if (timing is None) == row.configurable:
        raise ValueError("configurable settings require application timing")

    has_effective = row.effective is not _MISSING
    unavailable = _text(row.unavailable, optional=True)
    if has_effective == (unavailable is not None):
        raise ValueError("settings row must be effective or unavailable")
    source = _text(row.source, optional=True)
    if has_effective != (source is not None):
        raise ValueError("effective settings require a source")

    projected: dict[str, Any] = {
        "key": key,
        "configurable": row.configurable,
        "manual_ref": manual_ref,
        "sensitive": row.sensitive,
        "has_default": row.default is not _MISSING,
    }
    if config_key is not None:
        projected["config_key"] = config_key
    if timing is not None:
        projected["application_timing"] = timing
    if has_effective:
        projected["effective"] = REDACTED_VALUE if row.sensitive else row.effective
        projected["source"] = source
    else:
        projected["unavailable"] = unavailable
    if row.default is not _MISSING:
        projected["default"] = REDACTED_VALUE if row.sensitive else row.default
    return projected


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
    size = len(b'{"settings":[') + len(b'],"status":"ok"}')
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
    return {"status": "ok", "settings": rows}


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

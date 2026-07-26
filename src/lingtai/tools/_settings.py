"""Private shared reader for Agent-owned no-op tool settings placeholders.

The placeholder file is deliberately metadata-only.  A present, valid v1 file
proves that an Agent-owned settings snapshot was read, but it cannot select or
enable any tool behavior.  Individual tools may later add their own real
settings reader when a configurable choice is actually authorized.
"""
from __future__ import annotations

import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_SETTINGS_BYTES = 64 * 1024
SETTINGS_SCHEMA_VERSION = 1
_TOOL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class SettingsError(ValueError):
    """A placeholder settings snapshot was malformed or unsafe to use."""


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    """Immutable evidence for one reread of one tool's settings file."""

    source: str
    revision: str
    digest: str | None
    error: str | None = None


def valid_tool_name(value: Any) -> bool:
    """Return whether *value* is safe as one bounded settings path component."""
    return isinstance(value, str) and _TOOL_NAME.fullmatch(value) is not None


def settings_path(agent: Any, tool_name: str) -> Path:
    """Return the fixed Agent-owned ``settings/<tool_name>.json`` path."""
    if not valid_tool_name(tool_name):
        raise ValueError("tool name must be a bounded path component")
    return Path(agent._working_dir) / "settings" / f"{tool_name}.json"


def _bounded_error(exc: Exception) -> str:
    """Render a bounded diagnostic without echoing host paths or file content."""
    if isinstance(exc, OSError):
        return f"settings file could not be read ({type(exc).__name__})"
    text = str(exc).replace("\n", " ").strip()
    return (text or "invalid settings")[:240]


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate JSON object members instead of accepting last-wins data."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError("duplicate settings field")
        result[key] = value
    return result


def _read_stable(path: Path) -> tuple[bytes, str]:
    """Read one bounded regular-file snapshot and its content revision."""
    try:
        first = path.lstat()
    except FileNotFoundError:
        return b"", "missing"
    except OSError:
        raise

    if stat.S_ISLNK(first.st_mode) or not stat.S_ISREG(first.st_mode):
        raise SettingsError("settings file must be a regular file")
    if first.st_size > MAX_SETTINGS_BYTES:
        raise SettingsError("settings file exceeds the bounded size")

    # Open by path only after lstat, then compare the path identity and metadata
    # again.  Replacements, symlink swaps, growth, and ordinary in-place writes
    # are therefore rejected rather than partially accepted.
    try:
        with path.open("rb") as handle:
            raw = handle.read(MAX_SETTINGS_BYTES + 1)
    except FileNotFoundError as exc:
        raise SettingsError("settings snapshot changed during read") from exc

    try:
        second = path.lstat()
    except FileNotFoundError as exc:
        raise SettingsError("settings snapshot changed during read") from exc

    if stat.S_ISLNK(second.st_mode) or not stat.S_ISREG(second.st_mode):
        raise SettingsError("settings snapshot changed during read")
    if (
        len(raw) > MAX_SETTINGS_BYTES
        or first.st_dev != second.st_dev
        or first.st_ino != second.st_ino
        or first.st_size != second.st_size
        or first.st_mtime_ns != second.st_mtime_ns
    ):
        raise SettingsError("settings snapshot changed during read")
    return raw, hashlib.sha256(raw).hexdigest()[:32]


def read_settings(agent: Any, tool_name: str) -> SettingsSnapshot:
    """Reread and strictly validate one tool's placeholder settings snapshot.

    Missing is a normal placeholder state.  A valid file contributes only its
    source/revision/hash evidence; it never changes behavior.  Every invocation
    performs a fresh filesystem read and does not cache a prior snapshot.
    """
    path = settings_path(agent, tool_name)
    digest: str | None = None
    try:
        raw, revision = _read_stable(path)
        if revision == "missing":
            return SettingsSnapshot("missing", "missing", None)
        digest = revision
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        if not isinstance(value, dict) or set(value) != {"schema_version"}:
            raise SettingsError("settings schema must contain only schema_version")
        if type(value["schema_version"]) is not int or value["schema_version"] != SETTINGS_SCHEMA_VERSION:
            raise SettingsError("settings schema_version must be integer 1")
        return SettingsSnapshot(f"settings/{tool_name}.json", revision, digest)
    except (OSError, UnicodeError, json.JSONDecodeError, SettingsError) as exc:
        # Malformed data is never silently converted to the missing state.  The
        # digest from a bounded stable read is retained as evidence when safe.
        return SettingsSnapshot(
            "settings_error",
            digest or "error",
            digest,
            _bounded_error(exc if isinstance(exc, Exception) else SettingsError("invalid settings")),
        )


def current_setting(snapshot: SettingsSnapshot, tool_name: str) -> dict[str, Any]:
    """Build the bounded, secret-free current-setting diagnostic for a tool."""
    if not valid_tool_name(tool_name):
        raise ValueError("tool name must be a bounded path component")
    return_value: dict[str, Any] = {
        "configurable": False,
        "placeholder": "no-op",
        "source": snapshot.source,
        "settings_revision": snapshot.revision,
        "settings_hash": snapshot.digest,
        "change_hint": (
            f"Edit settings/{tool_name}.json; changes apply on the next {tool_name} "
            "call; this no-op placeholder never changes tool behavior."
        ),
    }
    if snapshot.error:
        return_value["settings_error"] = snapshot.error
    return return_value

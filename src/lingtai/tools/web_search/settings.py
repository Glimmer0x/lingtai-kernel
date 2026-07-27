"""Strict per-Agent settings for the ``web`` capability's ``search`` action.

The settings file is intentionally a tiny selector, not a provider
configuration file.  Operators configure engines and credentials at setup;
an Agent-owned, action-owned ``settings/web.search.json`` may select only one
admitted engine.  There is no family-owned ``settings/web.json``; browse and
manual read no settings file at all.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

MAX_SETTINGS_BYTES = 64 * 1024
_ENGINE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
CHANGE_HINT = (
    "Edit settings/web.search.json; changes apply on the next web call; use "
    "web(action='manual', input={}, reasoning='load web guidance') for schema."
)


def valid_engine_name(value: Any) -> bool:
    """Return whether *value* uses the one bounded engine-selector grammar."""
    return isinstance(value, str) and _ENGINE_NAME.fullmatch(value) is not None


def bounded_env_name(value: Any) -> str | None:
    """Return a safe environment-variable name, or None for unbounded input."""
    if isinstance(value, str) and _ENV_NAME.fullmatch(value):
        return value
    return None


class SettingsError(ValueError):
    """A settings snapshot was absent, unstable, malformed, or disallowed."""


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    engine: str | None
    source: str
    revision: str
    digest: str | None
    error: str | None = None


def settings_path(agent: Any) -> Path:
    """Return the one fixed, action-owned settings path for ``search``."""
    return Path(agent._working_dir) / "settings" / "web.search.json"


def _bounded_error(exc: Exception) -> str:
    # OS errors commonly include the absolute path passed to ``open``. The
    # result contract exposes only the agent-relative settings path, never the
    # host filesystem location.
    if isinstance(exc, OSError):
        return f"settings/web.search.json could not be read ({type(exc).__name__})"
    text = str(exc).replace("\n", " ").strip()
    return (text or "invalid settings")[:240]


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError("duplicate settings field")
        result[key] = value
    return result


def _read_stable(path: Path) -> tuple[bytes, str]:
    try:
        first = path.lstat()
    except FileNotFoundError:
        return b"", "missing"
    if stat.S_ISLNK(first.st_mode) or not stat.S_ISREG(first.st_mode):
        raise SettingsError("settings/web.search.json must be a regular file")
    if first.st_size > MAX_SETTINGS_BYTES:
        raise SettingsError("settings/web.search.json exceeds the bounded size")
    # Open by path only after lstat: a changed link/non-regular file is rejected
    # rather than followed.  A second stat closes ordinary replacement races.
    with path.open("rb") as handle:
        raw = handle.read(MAX_SETTINGS_BYTES + 1)
    try:
        second = path.lstat()
    except FileNotFoundError as exc:
        raise SettingsError("settings snapshot changed during read") from exc
    if stat.S_ISLNK(second.st_mode) or not stat.S_ISREG(second.st_mode):
        raise SettingsError("settings snapshot changed during read")
    if (
        len(raw) > MAX_SETTINGS_BYTES
        or first.st_size != second.st_size
        or first.st_ino != second.st_ino
        or first.st_mtime_ns != second.st_mtime_ns
    ):
        raise SettingsError("settings snapshot changed during read")
    digest = hashlib.sha256(raw).hexdigest()[:32]
    return raw, digest


def read_settings(
    agent: Any,
    admitted: Mapping[str, Any],
    default_engine: str | None,
    default_source: str = "built_in_default",
) -> SettingsSnapshot:
    """Read and validate one complete settings snapshot for the current call.

    ``default_source`` is computed once while composing the operator config and
    is passed through unchanged; this reader must not infer it from the engine.
    """
    path = settings_path(agent)
    try:
        raw, revision = _read_stable(path)
        if revision == "missing":
            return SettingsSnapshot(default_engine, default_source, "missing", None)
        text = raw.decode("utf-8")
        value = json.loads(text, object_pairs_hook=_pairs)
        if not isinstance(value, dict) or set(value) != {"schema_version", "engine"}:
            raise SettingsError("settings schema must contain only schema_version and engine")
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise SettingsError("settings schema_version must be integer 1")
        engine = value["engine"]
        if not isinstance(engine, str) or not _ENGINE_NAME.fullmatch(engine):
            raise SettingsError("settings engine must be a bounded engine name")
        if engine not in admitted:
            raise SettingsError("settings selected engine is not operator-admitted")
        return SettingsSnapshot(engine, "settings/web.search.json", revision, revision)
    except (OSError, UnicodeError, json.JSONDecodeError, SettingsError) as exc:
        # A malformed/changed file is never silently treated as missing.
        digest: str | None = None
        try:
            if path.is_file() and not path.is_symlink():
                with path.open("rb") as handle:
                    digest = hashlib.sha256(handle.read(MAX_SETTINGS_BYTES)).hexdigest()[:32]
        except OSError:
            pass
        return SettingsSnapshot(
            None,
            "settings_error",
            digest or "error",
            digest,
            _bounded_error(exc if isinstance(exc, Exception) else SettingsError("invalid settings")),
        )


def current_setting(snapshot: SettingsSnapshot, admitted: Mapping[str, Any], statuses: Mapping[str, str]) -> dict[str, Any]:
    """Build a bounded, secret-free diagnostic block."""
    available = []
    for name, status in statuses.items():
        item = {"name": str(name)[:64], "status": str(status)[:40]}
        # An env-var *name* is configuration metadata, not a credential. Show it
        # only for a missing credential and only when bounded; never inspect or
        # expose its value here.
        if item["status"] == "credential_missing":
            env_name = bounded_env_name(getattr(admitted.get(name), "api_key_env", None))
            if env_name:
                item["api_key_env"] = env_name
        available.append(item)
    available.sort(key=lambda item: item["name"])
    block: dict[str, Any] = {
        "engine": snapshot.engine,
        "search_engine": snapshot.engine,
        "selected_engine": snapshot.engine,
        "source": snapshot.source,
        "available_engines": available,
        "available_engine_names": [item["name"] for item in available],
        "available_engine_status": {item["name"]: item["status"] for item in available},
        "settings_revision": snapshot.revision,
        "settings_hash": snapshot.digest,
        "change_hint": CHANGE_HINT,
    }
    if snapshot.error:
        block["settings_error"] = snapshot.error
    return block

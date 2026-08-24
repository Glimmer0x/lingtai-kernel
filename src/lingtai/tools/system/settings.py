"""System-owned cache-miss budget settings.

This is the complete family-local reader for ``settings/system.json``.  It is
intentionally narrow: one closed versioned document, one environment override,
and one resolved positive integer projected through ``lingtai.Agent``.  It is
not a generic settings framework and never writes configuration.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

CACHE_MISS_BUDGET_ENV = "LINGTAI_CACHE_MISS_BUDGET"
CACHE_MISS_BUDGET_DEFAULT = 2_000_000
SYSTEM_SETTINGS_RELATIVE_PATH = "settings/system.json"
SYSTEM_SETTINGS_MAX_BYTES = 64 * 1024
SYSTEM_SETTINGS_SCHEMA_VERSION = 1
_SYSTEM_SETTINGS_KEYS = frozenset(("schema_version", "cache_miss_budget"))


class _DuplicateSettingsKey(ValueError):
    """A JSON object repeated a key instead of forming one closed document."""


@dataclass(frozen=True, slots=True)
class _SettingsRead:
    budget: int | None
    problem_signature: str | None
    problem: str | None


@dataclass(slots=True)
class _AgentSettingsState:
    """Per-agent serialization and diagnostic-dedup state."""

    lock: threading.RLock = field(default_factory=threading.RLock)
    problem_signature: str | None = None


_STATE_ATTRIBUTE = "_system_settings_state"
_STATE_CREATION_LOCK = threading.Lock()


def _agent_settings_state(agent: Any) -> _AgentSettingsState:
    """Return one lazily-created settings state object for *agent*."""
    try:
        state = getattr(agent, _STATE_ATTRIBUTE, None)
    except Exception:
        state = None
    if isinstance(state, _AgentSettingsState):
        return state

    # Attribute creation is itself serialized so two first-use metadata workers
    # cannot install different locks on the same Agent.
    with _STATE_CREATION_LOCK:
        try:
            state = getattr(agent, _STATE_ATTRIBUTE, None)
        except Exception:
            state = None
        if isinstance(state, _AgentSettingsState):
            return state
        state = _AgentSettingsState()
        try:
            setattr(agent, _STATE_ATTRIBUTE, state)
        except Exception:
            # Production ``lingtai.Agent`` is mutable.  This fallback keeps a
            # direct immutable test double safe, though it cannot retain dedup
            # state between independent calls.
            pass
        return state


def _settings_path(agent: Any) -> Path | None:
    """Return System's one fixed family-settings path when workdir is available."""
    try:
        root = getattr(agent, "_working_dir", None)
    except Exception:
        root = None
    if root is None:
        try:
            root = getattr(agent, "working_dir", None)
        except Exception:
            root = None
    if root is None:
        return None
    return Path(root) / "settings" / "system.json"


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate keys instead of accepting JSON's last-value-wins default."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateSettingsKey("duplicate_key")
        result[key] = value
    return result


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    """Return the identity and mutation fields used by the stable-read check."""
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _invalid(
    problem: str,
    *,
    raw: bytes | None = None,
    detail: str = "",
) -> _SettingsRead:
    """Build a stable, redaction-safe signature for one invalid observation."""
    digest = hashlib.sha256()
    digest.update(problem.encode("ascii", errors="replace"))
    digest.update(b"\0")
    if raw is not None:
        digest.update(hashlib.sha256(raw).digest())
    if detail:
        digest.update(detail.encode("utf-8", errors="replace"))
    return _SettingsRead(None, f"{problem}:{digest.hexdigest()[:32]}", problem)


def _read_settings(agent: Any) -> _SettingsRead:
    """Boundedly read and validate one stable System settings snapshot."""
    path = _settings_path(agent)
    if path is None:
        return _SettingsRead(None, None, None)

    try:
        first = path.lstat()
    except FileNotFoundError:
        return _SettingsRead(None, None, None)
    except OSError as exc:
        return _invalid("unreadable", detail=type(exc).__name__)

    first_identity = _stat_identity(first)
    if not stat.S_ISREG(first.st_mode):
        return _invalid("not_regular", detail=repr(first_identity))
    if first.st_size > SYSTEM_SETTINGS_MAX_BYTES:
        return _invalid("oversize", detail=repr(first_identity))

    raw: bytes | None = None
    try:
        with path.open("rb") as handle:
            opened_before = os.fstat(handle.fileno())
            opened_before_identity = _stat_identity(opened_before)
            if (
                not stat.S_ISREG(opened_before.st_mode)
                or opened_before_identity != first_identity
            ):
                return _invalid(
                    "unstable_read",
                    detail=repr((first_identity, opened_before_identity)),
                )
            raw = handle.read(SYSTEM_SETTINGS_MAX_BYTES + 1)
            opened_after = os.fstat(handle.fileno())
    except OSError as exc:
        return _invalid("unreadable", detail=type(exc).__name__)

    opened_after_identity = _stat_identity(opened_after)
    if len(raw) > SYSTEM_SETTINGS_MAX_BYTES:
        return _invalid("oversize", raw=raw, detail=repr(opened_after_identity))

    try:
        final = path.lstat()
    except OSError as exc:
        return _invalid(
            "unstable_read",
            raw=raw,
            detail=type(exc).__name__,
        )
    final_identity = _stat_identity(final)
    if (
        not stat.S_ISREG(final.st_mode)
        or opened_before_identity != opened_after_identity
        or opened_after_identity != final_identity
        or len(raw) != opened_after.st_size
    ):
        return _invalid(
            "unstable_read",
            raw=raw,
            detail=repr(
                (opened_before_identity, opened_after_identity, final_identity)
            ),
        )

    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except UnicodeError:
        return _invalid("invalid_utf8", raw=raw)
    except _DuplicateSettingsKey:
        return _invalid("duplicate_key", raw=raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return _invalid("malformed_json", raw=raw)

    if not isinstance(value, dict):
        return _invalid("not_object", raw=raw)
    if set(value) != _SYSTEM_SETTINGS_KEYS:
        return _invalid("invalid_schema", raw=raw)

    schema_version = value["schema_version"]
    if type(schema_version) is not int:
        return _invalid("invalid_schema_version", raw=raw)
    if schema_version != SYSTEM_SETTINGS_SCHEMA_VERSION:
        return _invalid("unsupported_schema_version", raw=raw)

    budget = value["cache_miss_budget"]
    if type(budget) is not int or budget <= 0:
        return _invalid("invalid_value", raw=raw)
    return _SettingsRead(budget, None, None)


def _record_problem(
    agent: Any,
    state: _AgentSettingsState,
    read: _SettingsRead,
) -> None:
    """Transition and diagnose one problem while the per-agent lock is held."""
    signature = read.problem_signature
    if state.problem_signature == signature:
        return

    # A valid or missing observation clears prior invalid state.  If that same
    # problem returns after an intervening repair/removal, it is diagnosed again.
    state.problem_signature = signature
    if signature is None:
        return

    log = getattr(agent, "_log", None)
    if not callable(log):
        return
    try:
        log(
            "cache_miss_budget_settings_invalid",
            settings_path=SYSTEM_SETTINGS_RELATIVE_PATH,
            reason=read.problem,
            fallback_budget=CACHE_MISS_BUDGET_DEFAULT,
        )
    except Exception:
        # Configuration is a soft steering input.  A diagnostic sink failure
        # cannot block metadata construction or change the fixed fallback.
        pass


def resolve_cache_miss_budget(agent: Any) -> int:
    """Return live valid env > live valid System file > fixed default.

    A valid environment value returns before any per-agent state creation or
    filesystem operation, so a shadowed file is neither read nor diagnosed.
    Invalid environment input is treated as unset.  The file read and diagnostic
    transition are serialized together per Agent.
    """
    env_raw = os.environ.get(CACHE_MISS_BUDGET_ENV, "").strip()
    if env_raw:
        try:
            env_budget = int(env_raw)
        except (TypeError, ValueError):
            env_budget = None
        if env_budget is not None and env_budget > 0:
            return env_budget

    state = _agent_settings_state(agent)
    with state.lock:
        read = _read_settings(agent)
        _record_problem(agent, state, read)
        if read.budget is not None:
            return read.budget
        return CACHE_MISS_BUDGET_DEFAULT


__all__ = [
    "CACHE_MISS_BUDGET_DEFAULT",
    "CACHE_MISS_BUDGET_ENV",
    "SYSTEM_SETTINGS_MAX_BYTES",
    "SYSTEM_SETTINGS_RELATIVE_PATH",
    "SYSTEM_SETTINGS_SCHEMA_VERSION",
    "resolve_cache_miss_budget",
]

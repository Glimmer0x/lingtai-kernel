"""Small, read-only settings owner for the System tool family.

Two closed document versions share ``<workdir>/settings/system.json``:

* **v1** — ``{"schema_version": 1, "cache_miss_budget": <positive int>}``.
  Parsed by :func:`_parse_settings`, which is deliberately unchanged: a valid
  v1 document keeps resolving byte-for-byte as before and v1 is never widened.
* **v2** — ``{"schema_version": 2, ...}`` carrying any subset of the ordinary
  runtime-policy fields in :data:`RUNTIME_POLICY_FIELDS`. Parsed by
  :func:`_parse_runtime_policy_v2`; one invalid field rejects the whole
  document so malformed System JSON can never partially override runtime
  values.

Ordinary boot/refresh fields resolve once through
:func:`resolve_runtime_policy` as ``valid env > valid v2 field > effective
manifest > default``. Two documented exceptions keep their live resolvers:
the cache-miss budget (``env > v1/v2 > 2_000_000``; legacy
``manifest.cache_miss_budget`` is never a source) and the notification cap
(Core parses ``LINGTAI_NOTIFICATION_MAX_CHARS`` itself, then asks the outer
Agent for the v2 file value through :func:`resolve_notification_max_chars`,
then its own 10,000 default; the 2048/10,000 clamp stays in Core).

Kernel-fixed context-pressure safety thresholds (0.85 / 1.0 / 3 rounds /
0.75) and the legacy ``molt_*`` fields are not System settings: any such key
makes a v2 document invalid.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

CACHE_MISS_BUDGET_ENV = "LINGTAI_CACHE_MISS_BUDGET"
DEFAULT_CACHE_MISS_BUDGET = 2_000_000
SYSTEM_SETTINGS_RELATIVE_PATH = Path("settings") / "system.json"
_SYSTEM_SETTINGS_SCHEMA_VERSION = 1

# Closed v2 runtime-policy document.
RUNTIME_POLICY_SCHEMA_VERSION = 2
RUNTIME_POLICY_FIELDS = (
    "context_limit",
    "max_rpm",
    "streaming",
    "aed_timeout",
    "max_aed_attempts",
    "snapshot_interval",
    "activeness",
    "cache_miss_budget",
    "notification_max_chars",
)
# Ordinary boot/refresh-time fields (the two live exceptions are excluded).
ORDINARY_POLICY_FIELDS = (
    "context_limit",
    "max_rpm",
    "streaming",
    "aed_timeout",
    "max_aed_attempts",
    "snapshot_interval",
    "activeness",
)
CONTEXT_LIMIT_ENV = "LINGTAI_CONTEXT_LIMIT"
MAX_RPM_ENV = "LINGTAI_MAX_RPM"
STREAMING_ENV = "LINGTAI_STREAMING"
AED_TIMEOUT_ENV = "LINGTAI_AED_TIMEOUT"
MAX_AED_ATTEMPTS_ENV = "LINGTAI_MAX_AED_ATTEMPTS"
SNAPSHOT_INTERVAL_ENV = "LINGTAI_SNAPSHOT_INTERVAL"
ACTIVENESS_ENV = "LINGTAI_ACTIVENESS"
RUNTIME_POLICY_ENV = {
    "context_limit": CONTEXT_LIMIT_ENV,
    "max_rpm": MAX_RPM_ENV,
    "streaming": STREAMING_ENV,
    "aed_timeout": AED_TIMEOUT_ENV,
    "max_aed_attempts": MAX_AED_ATTEMPTS_ENV,
    "snapshot_interval": SNAPSHOT_INTERVAL_ENV,
    "activeness": ACTIVENESS_ENV,
}
# Environment spelling that turns snapshots off explicitly (case-insensitive).
SNAPSHOT_INTERVAL_OFF = "off"
# Legacy default for agents whose manifest predates ``max_rpm``; matches
# ``AgentConfig.max_rpm`` and the historical ``m.get("max_rpm", 60)`` reads.
DEFAULT_MAX_RPM = 60

SOURCE_ENV = "env"
SOURCE_SYSTEM = "system"
SOURCE_MANIFEST = "manifest"
SOURCE_DEFAULT = "default"


def _positive_int(value: Any) -> int | None:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except (TypeError, ValueError):
            return None
        if parsed > 0:
            return parsed
    return None


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _parse_settings(text: str) -> int | None:
    try:
        data = json.loads(text, object_pairs_hook=_closed_object)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or set(data) != {
        "schema_version",
        "cache_miss_budget",
    }:
        return None
    if (
        type(data["schema_version"]) is not int
        or data["schema_version"] != _SYSTEM_SETTINGS_SCHEMA_VERSION
    ):
        return None
    budget = data["cache_miss_budget"]
    return budget if type(budget) is int and budget > 0 else None


# --- v2 field validators -----------------------------------------------------
#
# Each validator returns ``(ok, normalized_value)``. ``ok`` is False for any
# domain violation, including booleans masquerading as numbers and non-finite
# floats (Python's json accepts ``NaN``/``Infinity`` literals).


def _is_int(value: Any) -> bool:
    return type(value) is int


def _is_finite_number(value: Any) -> bool:
    if type(value) is int:
        return True
    return type(value) is float and math.isfinite(value)


def _validate_context_limit(value: Any) -> tuple[bool, Any]:
    if value is None:
        return True, None
    return (_is_int(value) and value > 0), value


def _validate_max_rpm(value: Any) -> tuple[bool, Any]:
    return (_is_int(value) and value >= 0), value


def _validate_streaming(value: Any) -> tuple[bool, Any]:
    return (type(value) is bool), value


def _validate_aed_timeout(value: Any) -> tuple[bool, Any]:
    return (_is_finite_number(value) and value > 0), value


def _validate_max_aed_attempts(value: Any) -> tuple[bool, Any]:
    return (_is_int(value) and value >= 1), value


def _validate_snapshot_interval(value: Any) -> tuple[bool, Any]:
    if value is None:
        return True, None
    return (_is_finite_number(value) and value > 0), value


def _validate_activeness(value: Any) -> tuple[bool, Any]:
    if value is None:
        return True, None
    return (isinstance(value, str) and bool(value.strip())), value


def _validate_positive_int(value: Any) -> tuple[bool, Any]:
    return (_is_int(value) and value > 0), value


_V2_VALIDATORS = {
    "context_limit": _validate_context_limit,
    "max_rpm": _validate_max_rpm,
    "streaming": _validate_streaming,
    "aed_timeout": _validate_aed_timeout,
    "max_aed_attempts": _validate_max_aed_attempts,
    "snapshot_interval": _validate_snapshot_interval,
    "activeness": _validate_activeness,
    "cache_miss_budget": _validate_positive_int,
    "notification_max_chars": _validate_positive_int,
}


def _parse_runtime_policy_v2(text: str) -> dict[str, Any] | None:
    """Return the present, valid v2 fields, or ``None`` for any invalid document.

    Presence-aware: an absent key is not in the mapping, while an explicit JSON
    ``null`` on a nullable field (``context_limit``, ``snapshot_interval``,
    ``activeness``) is present with value ``None``. Unknown keys, duplicate
    keys, a wrong ``schema_version``, and any field-domain violation reject the
    whole document.
    """
    try:
        data = json.loads(text, object_pairs_hook=_closed_object)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or "schema_version" not in data:
        return None
    version = data["schema_version"]
    if type(version) is not int or version != RUNTIME_POLICY_SCHEMA_VERSION:
        return None
    if not set(data) - {"schema_version"} <= set(RUNTIME_POLICY_FIELDS):
        return None
    fields: dict[str, Any] = {}
    for key in RUNTIME_POLICY_FIELDS:
        if key not in data:
            continue
        ok, value = _V2_VALIDATORS[key](data[key])
        if not ok:
            return None
        fields[key] = value
    return fields


def _read_settings_text(working_dir: Any) -> str | None:
    path = Path(working_dir) / SYSTEM_SETTINGS_RELATIVE_PATH
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def read_runtime_policy_document(working_dir: Any) -> dict[str, Any]:
    """Return the valid v2 field mapping for *working_dir*, else ``{}``.

    A missing, unreadable, malformed, v1, or otherwise invalid document yields
    an empty mapping so nothing is partially applied.
    """
    text = _read_settings_text(working_dir)
    if text is None:
        return {}
    fields = _parse_runtime_policy_v2(text)
    return fields if fields is not None else {}


# --- environment parsers ------------------------------------------------------
#
# Each parser returns ``(ok, value)``; ``ok`` False means "unset or invalid,
# fall through to the next layer". Values are always strings from the
# process environment, so no boolean-masquerade guard is needed.

_TRUE_WORDS = {"1", "true", "yes", "on"}
_FALSE_WORDS = {"0", "false", "no", "off"}


def _env_raw(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    return raw if raw else None


def _env_positive_int(name: str) -> tuple[bool, Any]:
    raw = _env_raw(name)
    if raw is None:
        return False, None
    try:
        value = int(raw)
    except ValueError:
        return False, None
    return (value > 0), value


def _env_nonnegative_int(name: str) -> tuple[bool, Any]:
    raw = _env_raw(name)
    if raw is None:
        return False, None
    try:
        value = int(raw)
    except ValueError:
        return False, None
    return (value >= 0), value


def _env_min_int(name: str, minimum: int) -> tuple[bool, Any]:
    raw = _env_raw(name)
    if raw is None:
        return False, None
    try:
        value = int(raw)
    except ValueError:
        return False, None
    return (value >= minimum), value


def _env_positive_number(name: str) -> tuple[bool, Any]:
    raw = _env_raw(name)
    if raw is None:
        return False, None
    try:
        value: int | float = int(raw)
    except ValueError:
        try:
            value = float(raw)
        except ValueError:
            return False, None
    if not _is_finite_number(value) or value <= 0:
        return False, None
    return True, value


def _env_bool(name: str) -> tuple[bool, Any]:
    raw = _env_raw(name)
    if raw is None:
        return False, None
    word = raw.lower()
    if word in _TRUE_WORDS:
        return True, True
    if word in _FALSE_WORDS:
        return True, False
    return False, None


def _env_snapshot_interval(name: str) -> tuple[bool, Any]:
    raw = _env_raw(name)
    if raw is None:
        return False, None
    if raw.lower() == SNAPSHOT_INTERVAL_OFF:
        return True, None
    return _env_positive_number(name)


def _env_activeness(name: str) -> tuple[bool, Any]:
    raw = _env_raw(name)
    if raw is None:
        return False, None
    return True, raw


_ENV_PARSERS = {
    "context_limit": lambda: _env_positive_int(CONTEXT_LIMIT_ENV),
    "max_rpm": lambda: _env_nonnegative_int(MAX_RPM_ENV),
    "streaming": lambda: _env_bool(STREAMING_ENV),
    "aed_timeout": lambda: _env_positive_number(AED_TIMEOUT_ENV),
    "max_aed_attempts": lambda: _env_min_int(MAX_AED_ATTEMPTS_ENV, 1),
    "snapshot_interval": lambda: _env_snapshot_interval(SNAPSHOT_INTERVAL_ENV),
    "activeness": lambda: _env_activeness(ACTIVENESS_ENV),
}


# --- resolved policy -----------------------------------------------------------


def _policy_defaults() -> dict[str, Any]:
    from lingtai.kernel.config import AgentConfig

    defaults = AgentConfig()
    return {
        "context_limit": defaults.context_limit,
        "max_rpm": DEFAULT_MAX_RPM,
        "streaming": False,
        "aed_timeout": defaults.aed_timeout,
        "max_aed_attempts": defaults.max_aed_attempts,
        "snapshot_interval": defaults.snapshot_interval,
        "activeness": defaults.activeness,
    }


@dataclass(frozen=True)
class ResolvedRuntimePolicy:
    """Effective ordinary runtime policy plus per-field provenance.

    ``sources[field]`` is one of ``"env"``, ``"system"``, ``"manifest"``, or
    ``"default"``. Manifest values are taken as the effective manifest already
    validated by the init reader, so a manifest-sourced field reproduces the
    pre-policy ``manifest.get(...)`` behavior exactly.
    """

    context_limit: int | None
    max_rpm: int
    streaming: bool
    aed_timeout: float
    max_aed_attempts: int
    snapshot_interval: float | None
    activeness: str | None
    sources: Mapping[str, str] = field(default_factory=dict)

    def as_overrides(self) -> dict[str, Any]:
        """Return the ordinary fields as a plain mapping (no provenance)."""
        return {name: getattr(self, name) for name in ORDINARY_POLICY_FIELDS}


def resolve_runtime_policy(
    working_dir: Any, manifest: Mapping[str, Any] | None
) -> ResolvedRuntimePolicy:
    """Resolve the ordinary boot/refresh fields once for boot and refresh.

    Per field: valid env > valid v2 System field > effective manifest key
    (presence, not truthiness — a manifest ``null`` is a manifest value) >
    unchanged default. The manifest mapping is never mutated.
    """
    system_fields = read_runtime_policy_document(working_dir)
    manifest = manifest or {}
    defaults = _policy_defaults()
    values: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for name in ORDINARY_POLICY_FIELDS:
        ok, env_value = _ENV_PARSERS[name]()
        if ok:
            values[name], sources[name] = env_value, SOURCE_ENV
        elif name in system_fields:
            values[name], sources[name] = system_fields[name], SOURCE_SYSTEM
        elif name in manifest:
            values[name], sources[name] = manifest[name], SOURCE_MANIFEST
        else:
            values[name], sources[name] = defaults[name], SOURCE_DEFAULT
    return ResolvedRuntimePolicy(sources=sources, **values)


def resolve_cache_miss_budget(agent: Any) -> int:
    """Resolve live env, then System JSON (v1 or v2), then the fixed default.

    ``manifest.cache_miss_budget`` is deliberately not a source.
    """
    env_budget = _positive_int(os.environ.get(CACHE_MISS_BUDGET_ENV))
    if env_budget is not None:
        return env_budget

    text = _read_settings_text(agent._working_dir)
    budget = _parse_settings(text) if text is not None else None
    if budget is None and text is not None:
        fields = _parse_runtime_policy_v2(text)
        if fields is not None:
            budget = fields.get("cache_miss_budget")
    return budget if budget is not None else DEFAULT_CACHE_MISS_BUDGET


def resolve_notification_max_chars(agent: Any) -> int | None:
    """Return the v2 ``notification_max_chars`` file value, or ``None``.

    Core owns ``LINGTAI_NOTIFICATION_MAX_CHARS`` (higher precedence), the
    2048/10,000 clamp, and the 10,000 default; this resolver only supplies the
    System-owned file layer between them.
    """
    return read_runtime_policy_document(agent._working_dir).get(
        "notification_max_chars"
    )

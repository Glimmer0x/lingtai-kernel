"""Small, technology-neutral declarations for opt-in tool settings."""
from __future__ import annotations

import math
import re
from dataclasses import InitVar, dataclass, field
from typing import Any, Callable, Protocol

SETTINGS_ACTION = "settings"
REDACTED_VALUE = "<redacted>"
MAX_STRING_BYTES = 16_384
MAX_STRING_CHARACTERS = 16_384
MAX_STRING_LIST_ITEMS = 1_024
MAX_STRING_LIST_BYTES = 1_048_576
MAX_INTEGER_ABS = 9_223_372_036_854_775_807
MAX_CONTRACT_SPECS = 1_024
MAX_METADATA_CHARACTERS = 1_024
MAX_RECEIPT_CHANGED_KEYS = MAX_CONTRACT_SPECS

VALUE_KINDS = frozenset({"boolean", "integer", "number", "string", "string-list", "opaque"})
CALLER_MUTABILITIES = frozenset({"mutable", "immutable", "owner-only"})
APPLICATION_TIMINGS = frozenset(
    {"live-now", "next-operation", "prompt-rebuild", "owner-rebuild", "system-refresh", "full-relaunch"}
)
SENSITIVITIES = frozenset({"public", "redacted"})
SOURCE_LABELS = frozenset({"caller", "environment", "default", "owner"})
DIAGNOSTIC_CODES = frozenset(
    {"APPLICATION_FAILED", "IMMUTABLE_SETTING", "INVALID_INPUT",
     "INVALID_OWNER_RESULT", "INVALID_VALUE", "OPAQUE_SETTING",
     "OWNER_MUTATION_UNKNOWN", "OWNER_ONLY_SETTING", "OWNER_RESOLVE_FAILED",
     "SETTING_UNAVAILABLE", "UNKNOWN_SETTING"}
)
STATE_DIAGNOSTIC_CODES = frozenset({"OWNER_RESOLVE_FAILED", "SETTING_UNAVAILABLE"})

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_OPERATIONS = frozenset({"set", "reset"})
_COMMIT_STATES = frozenset({"not-committed", "committed", "unknown"})
_APPLICATION_STATES = frozenset({"applied", "pending", "failed", "unknown"})
_MISSING = object()
_UNAVAILABLE = object()


def _bounded_string(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("value must be a string")
    try:
        byte_count = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError("value must be valid UTF-8") from exc
    if len(value) > MAX_STRING_CHARACTERS or byte_count > MAX_STRING_BYTES:
        raise ValueError("string value exceeds the contract bound")
    return value


def _bounded_metadata(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8") from exc
    if len(value) > MAX_METADATA_CHARACTERS:
        raise ValueError(f"{label} exceeds the metadata character bound")
    return value


def normalize_setting_value(value_kind: str, value: Any) -> Any:
    """Validate and normalize one bounded, non-recursive contract value."""
    if value_kind == "boolean":
        if type(value) is not bool:
            raise ValueError("value must be boolean")
        return value
    if value_kind == "integer":
        if type(value) is not int or abs(value) > MAX_INTEGER_ABS:
            raise ValueError("value must be a bounded integer")
        return value
    if value_kind == "number":
        if type(value) is int:
            if abs(value) > MAX_INTEGER_ABS:
                raise ValueError("value must be a bounded number")
            return value
        if type(value) is not float or not math.isfinite(value):
            raise ValueError("value must be a finite number")
        return value
    if value_kind == "string":
        return _bounded_string(value)
    if value_kind == "string-list":
        if not isinstance(value, (list, tuple)):
            raise ValueError("value must be a string list")
        if len(value) > MAX_STRING_LIST_ITEMS:
            raise ValueError("string list exceeds the item bound")
        normalized = tuple(_bounded_string(item) for item in value)
        if sum(len(item.encode("utf-8")) for item in normalized) > MAX_STRING_LIST_BYTES:
            raise ValueError("string list exceeds the aggregate byte bound")
        return normalized
    if value_kind == "opaque":
        if type(value) is bool:
            return value
        if type(value) is int:
            if abs(value) > MAX_INTEGER_ABS:
                raise ValueError("opaque integer exceeds the contract bound")
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("opaque number must be finite")
            return value
        if isinstance(value, str):
            return _bounded_string(value)
        if isinstance(value, (list, tuple)):
            return normalize_setting_value("string-list", value)
        raise ValueError("opaque value must be a bounded scalar or string list")
    raise ValueError(f"unsupported value kind {value_kind!r}")


@dataclass(frozen=True, slots=True)
class SettingSpec:
    """One declaration-owned setting; the missing-default marker stays private."""

    key: str
    value_kind: str
    env: str | None
    precedence: tuple[str, ...]
    caller_mutability: str
    application_timing: str
    sensitivity: str
    comment: str
    default: InitVar[Any] = _MISSING
    _default: Any = field(init=False, repr=False)

    def __post_init__(self, default: Any) -> None:
        try:
            key = _bounded_metadata(self.key, "setting key")
            comment = _bounded_metadata(self.comment, "setting comment")
            env = None if self.env is None else _bounded_metadata(self.env, "setting environment")
        except ValueError as exc:
            raise ValueError(f"setting {self.key!r} has invalid declaration metadata") from exc
        invalid = (
            not _KEY_PATTERN.fullmatch(key)
            or self.value_kind not in VALUE_KINDS
            or (env is not None and not _ENV_PATTERN.fullmatch(env))
            or not isinstance(self.precedence, tuple)
            or not self.precedence
            or any(item not in SOURCE_LABELS for item in self.precedence)
            or len(set(self.precedence)) != len(self.precedence)
            or (("environment" in self.precedence) != (env is not None))
            or (("default" in self.precedence) != (default is not _MISSING))
            or self.caller_mutability not in CALLER_MUTABILITIES
            or self.application_timing not in APPLICATION_TIMINGS
            or self.sensitivity not in SENSITIVITIES
        )
        if invalid:
            raise ValueError(f"setting {self.key!r} has invalid declaration metadata")
        if self.value_kind == "opaque" and self.caller_mutability == "mutable":
            raise ValueError(f"opaque setting {self.key!r} must be immutable or owner-only")
        normalized = (_MISSING if default is _MISSING else
                      normalize_setting_value(self.value_kind, default))
        object.__setattr__(self, "_default", normalized)

    def __getattribute__(self, name: str) -> Any:
        if name == "default":
            raise AttributeError("default is projected through has_default/default_value")
        return object.__getattribute__(self, name)

    @property
    def has_default(self) -> bool:
        return self._default is not _MISSING

    def default_value(self) -> Any:
        if not self.has_default:
            raise ValueError(f"setting {self.key!r} has no default")
        return list(self._default) if isinstance(self._default, tuple) else self._default


@dataclass(frozen=True, slots=True)
class ToolSettingsContract:
    """Explicit opt-in, including the distinct zero-spec contract."""

    specs: tuple[SettingSpec, ...]
    _binding_identity: object = field(default_factory=object, init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self.specs, tuple) or any(
            not isinstance(item, SettingSpec) for item in self.specs
        ):
            raise ValueError("settings specs must be an immutable tuple of SettingSpec values")
        if len(self.specs) > MAX_CONTRACT_SPECS:
            raise ValueError("settings contract exceeds the spec-count bound")
        keys = [spec.key for spec in self.specs]
        envs = [spec.env for spec in self.specs if spec.env is not None]
        if len(keys) != len(set(keys)):
            raise ValueError("settings contract has a duplicate key")
        if len(envs) != len(set(envs)):
            raise ValueError("settings contract has a duplicate environment name")


@dataclass(frozen=True, slots=True)
class SettingState:
    """Owner-resolved runtime facts; static metadata remains in SettingSpec."""

    available: bool
    effective: InitVar[Any] = _UNAVAILABLE
    source: str | None = None
    diagnostic_code: str | None = None
    _effective: Any = field(init=False, repr=False)

    def __post_init__(self, effective: Any) -> None:
        if type(self.available) is not bool:
            raise ValueError("setting state availability must be boolean")
        if self.source is not None and self.source not in SOURCE_LABELS:
            raise ValueError("setting state source is not a closed source label")
        if self.diagnostic_code is not None and self.diagnostic_code not in STATE_DIAGNOSTIC_CODES:
            raise ValueError("setting state diagnostic code is not closed")
        if self.available:
            if effective is _UNAVAILABLE or self.source is None or self.diagnostic_code is not None:
                raise ValueError("available state requires an effective value and source only")
            normalized = normalize_setting_value("opaque", effective)
        else:
            if effective is not _UNAVAILABLE or self.source is not None or self.diagnostic_code is None:
                raise ValueError("unavailable state requires only a diagnostic code")
            normalized = _UNAVAILABLE
        object.__setattr__(self, "_effective", normalized)

    def __getattribute__(self, name: str) -> Any:
        if name == "effective":
            raise AttributeError("effective is projected through effective_value")
        return object.__getattribute__(self, name)

    def effective_value(self) -> Any:
        if not self.available:
            raise ValueError("unavailable setting has no effective value")
        return list(self._effective) if isinstance(self._effective, tuple) else self._effective


@dataclass(frozen=True, slots=True)
class SettingMutationReceipt:
    """Truthful owner receipt for one mutation attempt."""

    operation: str
    key: str
    commit_state: str
    application_state: str
    changed_keys: tuple[str, ...] = ()
    error_code: str | None = None

    def __post_init__(self) -> None:
        if self.operation not in _OPERATIONS:
            raise ValueError("setting receipt has invalid operation")
        if (not isinstance(self.key, str) or len(self.key) > MAX_METADATA_CHARACTERS
                or not _KEY_PATTERN.fullmatch(self.key)):
            raise ValueError("setting receipt has invalid key")
        if self.commit_state not in _COMMIT_STATES or self.application_state not in _APPLICATION_STATES:
            raise ValueError("setting receipt has invalid state")
        if (not isinstance(self.changed_keys, tuple)
                or len(self.changed_keys) > MAX_RECEIPT_CHANGED_KEYS
                or any(not isinstance(key, str) or len(key) > MAX_METADATA_CHARACTERS
                       or not _KEY_PATTERN.fullmatch(key) for key in self.changed_keys)):
            raise ValueError("setting receipt changed_keys must be bounded canonical tuple keys")
        if len(set(self.changed_keys)) != len(self.changed_keys):
            raise ValueError("setting receipt has duplicate changed keys")
        if self.error_code is not None and self.error_code not in DIAGNOSTIC_CODES:
            raise ValueError("setting receipt error code is not closed")
        if self.commit_state == "not-committed":
            if (self.application_state != "failed" or self.changed_keys
                    or self.error_code is None):
                raise ValueError("not-committed receipt must be a coded failure with no changes")
        elif self.commit_state == "unknown":
            if (self.application_state != "unknown" or self.changed_keys
                    or self.error_code != "OWNER_MUTATION_UNKNOWN"):
                raise ValueError(
                    "unknown commit requires unknown application, no claimed changes, "
                    "and OWNER_MUTATION_UNKNOWN"
                )
        elif self.application_state == "failed" and self.error_code != "APPLICATION_FAILED":
            raise ValueError("committed application failure requires APPLICATION_FAILED")
        elif self.application_state != "failed" and self.error_code is not None:
            raise ValueError("only failed or unknown receipts may carry an error code")


class SettingOwner(Protocol):
    def resolve(self, spec: SettingSpec) -> SettingState: ...
    def set(self, spec: SettingSpec, value: Any) -> SettingMutationReceipt: ...
    def reset(self, spec: SettingSpec) -> SettingMutationReceipt: ...


def settings_input_schema() -> dict[str, Any]:
    """Return a fresh strict schema for inventory, set, and reset."""
    return {
        "type": "object",
        "properties": {
            "set": {"type": "string"}, "value": {}, "reset": {"type": "string"}
        },
        "additionalProperties": False,
        "oneOf": [
            {"title": "inventory settings", "properties": {},
             "additionalProperties": False},
            {"title": "set one setting",
             "properties": {"set": {"type": "string"}, "value": {}},
             "required": ["set", "value"], "additionalProperties": False},
            {"title": "reset one setting",
             "properties": {"reset": {"type": "string"}},
             "required": ["reset"], "additionalProperties": False},
        ],
    }


def _bound_settings_matches(
    bound_handler: Callable[..., Any], contract: ToolSettingsContract | None
) -> bool:
    """Compare against the controller reachable from the actual bound handler."""
    family = getattr(bound_handler, "__self__", None)
    child_getter = getattr(family, "_tool_settings_handler", None)
    try:
        child_handler = child_getter() if callable(child_getter) else None
        identity_getter = getattr(child_handler, "_tool_settings_identity", None)
        identity = identity_getter() if callable(identity_getter) else None
    except Exception:
        return False
    if contract is None:
        return identity is None
    return identity is contract._binding_identity

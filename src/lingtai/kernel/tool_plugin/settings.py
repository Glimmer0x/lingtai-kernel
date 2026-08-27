"""Small, technology-neutral declarations for opt-in tool settings SHOW."""
from __future__ import annotations

import math
import re
from dataclasses import InitVar, dataclass, field
from typing import Any, Callable, Protocol

SETTINGS_ACTION = "settings"
REDACTED_VALUE = "<redacted>"
SETTINGS_RESPONSE_TOO_LARGE = "SETTINGS_RESPONSE_TOO_LARGE"
MAX_SETTINGS_RESPONSE_BYTES = 65_536
MAX_STRING_BYTES = 16_384
MAX_STRING_CHARACTERS = 16_384
MAX_STRING_LIST_ITEMS = 1_024
MAX_STRING_LIST_BYTES = 1_048_576
MAX_INTEGER_ABS = 9_223_372_036_854_775_807
MAX_CONTRACT_SPECS = 1_024
MAX_METADATA_CHARACTERS = 1_024
MAX_PRECEDENCE_ENTRIES = 32

VALUE_KINDS = frozenset({"boolean", "integer", "number", "string", "string-list", "opaque"})
APPLICATION_TIMINGS = frozenset(
    {
        "live-now",
        "next-operation",
        "prompt-rebuild",
        "owner-rebuild",
        "system-refresh",
        "full-relaunch",
    }
)
SENSITIVITIES = frozenset({"public", "redacted"})
STATE_DIAGNOSTIC_CODES = frozenset({"OWNER_RESOLVE_FAILED", "SETTING_UNAVAILABLE"})

_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")
_ENV_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
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


def _bounded_metadata(value: Any, label: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{label} must be valid UTF-8") from exc
    if len(value) > MAX_METADATA_CHARACTERS:
        raise ValueError(f"{label} exceeds the metadata character bound")
    if nonempty and not value.strip():
        raise ValueError(f"{label} must be non-empty")
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
    configurable: bool
    env: str | None
    precedence: tuple[str, ...]
    application_timing: str | None
    sensitivity: str
    manual_ref: str
    default: InitVar[Any] = _MISSING
    _default: Any = field(init=False, repr=False)

    def __post_init__(self, default: Any) -> None:
        try:
            key = _bounded_metadata(self.key, "setting key")
            _bounded_metadata(self.manual_ref, "setting manual reference", nonempty=True)
            env = (
                None
                if self.env is None
                else _bounded_metadata(self.env, "setting environment")
            )
            if (
                not isinstance(self.precedence, tuple)
                or not self.precedence
                or len(self.precedence) > MAX_PRECEDENCE_ENTRIES
            ):
                raise ValueError("setting precedence must be a bounded non-empty tuple")
            precedence = tuple(
                _bounded_metadata(item, "setting precedence label", nonempty=True)
                for item in self.precedence
            )
        except ValueError as exc:
            raise ValueError(f"setting {self.key!r} has invalid declaration metadata") from exc
        invalid = (
            not _KEY_PATTERN.fullmatch(key)
            or self.value_kind not in VALUE_KINDS
            or type(self.configurable) is not bool
            or (env is not None and not _ENV_PATTERN.fullmatch(env))
            or len(set(precedence)) != len(precedence)
            or (
                self.configurable
                and self.application_timing not in APPLICATION_TIMINGS
            )
            or (not self.configurable and self.application_timing is not None)
            or (not self.configurable and env is not None)
            or self.sensitivity not in SENSITIVITIES
        )
        if invalid:
            raise ValueError(f"setting {self.key!r} has invalid declaration metadata")
        normalized = (
            _MISSING
            if default is _MISSING
            else normalize_setting_value(self.value_kind, default)
        )
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
    """Explicit SHOW opt-in, including the distinct zero-spec contract."""

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
    """Owner-resolved current facts; static metadata remains in SettingSpec."""

    available: bool
    effective: InitVar[Any] = _UNAVAILABLE
    source: str | None = None
    diagnostic_code: str | None = None
    _effective: Any = field(init=False, repr=False)

    def __post_init__(self, effective: Any) -> None:
        if type(self.available) is not bool:
            raise ValueError("setting state availability must be boolean")
        if self.source is not None:
            _bounded_metadata(self.source, "setting state source", nonempty=True)
        if (
            self.diagnostic_code is not None
            and self.diagnostic_code not in STATE_DIAGNOSTIC_CODES
        ):
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


class SettingOwner(Protocol):
    """Resolve current state only; external configuration owners perform changes."""

    def resolve(self, spec: SettingSpec) -> SettingState: ...


def settings_input_schema() -> dict[str, Any]:
    """Return the fresh strict-empty schema for read-only inventory."""
    return {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
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

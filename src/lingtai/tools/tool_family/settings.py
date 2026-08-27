"""Read-only controller for an explicitly opted-in ToolPlugin settings action."""
from __future__ import annotations

import json
from typing import Any, Mapping

from lingtai.kernel.tool_plugin.settings import (
    MAX_SETTINGS_RESPONSE_BYTES,
    REDACTED_VALUE,
    SETTINGS_ACTION,
    SETTINGS_RESPONSE_TOO_LARGE,
    SettingOwner,
    SettingSpec,
    SettingState,
    ToolSettingsContract,
    normalize_setting_value,
    settings_input_schema,
)

from . import ChildTool

_MESSAGES = {
    "INVALID_INPUT": "settings accepts only the empty input object",
    "OWNER_RESOLVE_FAILED": "setting owner could not resolve effective state",
    "SETTING_UNAVAILABLE": "setting is currently unavailable",
    SETTINGS_RESPONSE_TOO_LARGE: (
        "complete settings inventory exceeds the 65536-byte canonical JSON bound"
    ),
}


def _diagnostic(code: str) -> dict[str, str]:
    return {"code": code, "message": _MESSAGES[code]}


def _row(spec: SettingSpec, state: SettingState) -> dict[str, Any]:
    row: dict[str, Any] = {
        "key": spec.key,
        "available": state.available,
        "value_kind": spec.value_kind,
        "configurable": spec.configurable,
        "precedence": list(spec.precedence),
        "sensitivity": spec.sensitivity,
        "manual_ref": spec.manual_ref,
        "has_default": spec.has_default,
    }
    if spec.application_timing is not None:
        row["application_timing"] = spec.application_timing
    if spec.env is not None:
        row["env"] = spec.env
    if state.available:
        row["source"] = state.source
        row["effective"] = (
            state.effective_value() if spec.sensitivity == "public" else REDACTED_VALUE
        )
    else:
        assert state.diagnostic_code is not None
        row["diagnostic"] = _diagnostic(state.diagnostic_code)
    if spec.has_default:
        row["default"] = (
            spec.default_value() if spec.sensitivity == "public" else REDACTED_VALUE
        )
    return row


def _canonical_json_size(value: Mapping[str, Any]) -> int:
    serialized = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return len(serialized.encode("utf-8"))


def _bounded_inventory_result(result: dict[str, Any]) -> dict[str, Any]:
    if _canonical_json_size(result) <= MAX_SETTINGS_RESPONSE_BYTES:
        return result
    failure = {
        "status": "failed",
        "error_code": SETTINGS_RESPONSE_TOO_LARGE,
        "message": _MESSAGES[SETTINGS_RESPONSE_TOO_LARGE],
        "max_bytes": MAX_SETTINGS_RESPONSE_BYTES,
    }
    if _canonical_json_size(failure) > MAX_SETTINGS_RESPONSE_BYTES:
        raise RuntimeError("settings response-bound diagnostic exceeds its own bound")
    return failure


class _SettingsController:
    def __init__(self, contract: ToolSettingsContract, owner: SettingOwner | None) -> None:
        self._contract = contract
        self._owner = owner
        self._specs = self._contract.specs

    def _tool_settings_identity(self) -> object:
        return self._contract._binding_identity

    def _resolve(self, spec: SettingSpec) -> tuple[SettingState, bool]:
        try:
            if self._owner is None:
                raise ValueError("missing owner")
            state = self._owner.resolve(spec)
            if type(state) is not SettingState:
                raise ValueError("wrong state type")
            if state.available:
                normalize_setting_value(spec.value_kind, state.effective_value())
                if state.source not in spec.precedence:
                    raise ValueError("source is not declared in precedence")
            elif state.diagnostic_code not in {
                "OWNER_RESOLVE_FAILED",
                "SETTING_UNAVAILABLE",
            }:
                raise ValueError("unavailable state has an invalid diagnostic")
            failed = (
                not state.available
                and state.diagnostic_code == "OWNER_RESOLVE_FAILED"
            )
            return state, failed
        except Exception:
            return SettingState(False, diagnostic_code="OWNER_RESOLVE_FAILED"), True

    def _inventory(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        resolve_failed = False
        result: dict[str, Any] = {"status": "ok", "settings": rows}
        for spec in self._specs:
            state, failed = self._resolve(spec)
            rows.append(_row(spec, state))
            resolve_failed = resolve_failed or failed
            result = {"status": "ok", "settings": rows}
            if resolve_failed:
                result.update(
                    status="failed",
                    error_code="OWNER_RESOLVE_FAILED",
                    message=_MESSAGES["OWNER_RESOLVE_FAILED"],
                )
            bounded = _bounded_inventory_result(result)
            if bounded is not result:
                return bounded
        return result

    def __call__(self, action_input: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(action_input, Mapping) or action_input:
            return {
                "status": "failed",
                "error_code": "INVALID_INPUT",
                "message": _MESSAGES["INVALID_INPUT"],
            }
        return self._inventory()


def build_settings_child(
    contract: ToolSettingsContract, owner: SettingOwner | None
) -> ChildTool:
    """Build the actual read-only child carrying the declaration identity."""
    if not isinstance(contract, ToolSettingsContract):
        raise ValueError("settings must be a ToolSettingsContract")
    if owner is not None and not callable(getattr(owner, "resolve", None)):
        raise ValueError("settings owner must provide callable resolve")
    if owner is None and contract.specs:
        raise ValueError("non-empty settings contract requires an owner")
    controller = _SettingsController(contract, owner)
    return ChildTool(
        name=SETTINGS_ACTION,
        input_schema=settings_input_schema(),
        handler=controller,
        title="settings inventory input",
    )

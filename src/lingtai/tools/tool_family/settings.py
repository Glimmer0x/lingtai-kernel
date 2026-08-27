"""Generic controller for an explicitly opted-in ToolPlugin settings action."""
from __future__ import annotations

from typing import Any, Mapping

from lingtai.kernel.tool_plugin.settings import (
    REDACTED_VALUE,
    SETTINGS_ACTION,
    SettingMutationReceipt,
    SettingOwner,
    SettingSpec,
    SettingState,
    ToolSettingsContract,
    normalize_setting_value,
    settings_input_schema,
)

from . import ChildTool

_MESSAGES = {
    "APPLICATION_FAILED": "the change was committed but application failed",
    "IMMUTABLE_SETTING": "setting is immutable",
    "INVALID_INPUT": "use inventory {}, set, or reset with exactly the documented fields",
    "INVALID_OWNER_RESULT": "setting owner returned an invalid receipt",
    "INVALID_VALUE": "value is invalid for this setting",
    "OPAQUE_SETTING": "opaque setting is inventory-only",
    "OWNER_MUTATION_UNKNOWN": "the owner was invoked; commit outcome is unknown",
    "OWNER_ONLY_SETTING": "setting may be changed only by its owner",
    "OWNER_RESOLVE_FAILED": "setting owner could not resolve effective state",
    "SETTING_UNAVAILABLE": "setting is currently unavailable",
    "UNKNOWN_SETTING": "setting is not declared by this family",
}


def _diagnostic(code: str | None) -> dict[str, str] | None:
    return None if code is None else {"code": code, "message": _MESSAGES[code]}


def _row(spec: SettingSpec, state: SettingState) -> dict[str, Any]:
    row: dict[str, Any] = {
        "key": spec.key, "available": state.available,
        "caller_mutability": spec.caller_mutability,
        "application_timing": spec.application_timing, "sensitivity": spec.sensitivity,
        "diagnostic": _diagnostic(state.diagnostic_code),
    }
    if spec.sensitivity != "public":
        if state.available:
            row["effective"] = REDACTED_VALUE
        if spec.has_default:
            row["default"] = REDACTED_VALUE
        return row
    row.update(
        value_kind=spec.value_kind, env=spec.env, source=state.source,
        precedence=list(spec.precedence), comment=spec.comment,
        has_default=spec.has_default,
    )
    if state.available:
        row["effective"] = state.effective_value()
    if spec.has_default:
        row["default"] = spec.default_value()
    return row


class _SettingsController:
    def __init__(self, contract: ToolSettingsContract, owner: SettingOwner | None) -> None:
        self._contract = contract
        self._owner = owner
        self._specs = self._contract.specs
        self._by_key = {spec.key: spec for spec in self._specs}

    def _tool_settings_identity(self) -> object:
        return self._contract._binding_identity

    def _resolve(self, spec: SettingSpec) -> tuple[SettingState, bool]:
        try:
            if self._owner is None:
                raise ValueError("missing owner")
            state = self._owner.resolve(spec)
            if not isinstance(state, SettingState):
                raise ValueError("wrong state type")
            if state.available:
                normalize_setting_value(spec.value_kind, state.effective_value())
                if state.source not in spec.precedence:
                    raise ValueError("source is not declared in precedence")
                if state.source == "default" and not spec.has_default:
                    raise ValueError("default source without default")
            return state, False
        except Exception:
            return SettingState(False, diagnostic_code="OWNER_RESOLVE_FAILED"), True

    def _inventory(self) -> tuple[list[dict[str, Any]], bool]:
        rows: list[dict[str, Any]] = []
        failed = False
        for spec in self._specs:
            state, bad = self._resolve(spec)
            rows.append(_row(spec, state))
            failed = failed or bad
        return rows, failed

    def _result(self, status: str, *, error_code: str | None = None,
                mutation: dict[str, Any] | None = None) -> dict[str, Any]:
        rows, resolve_failed = self._inventory()
        result: dict[str, Any] = {"status": status, "settings": rows}
        if error_code is not None:
            result.update(error_code=error_code, message=_MESSAGES[error_code])
        if mutation is not None:
            result["mutation"] = mutation
        if resolve_failed:
            if mutation is None and error_code is None:
                result.update(status="failed", error_code="OWNER_RESOLVE_FAILED",
                              message=_MESSAGES["OWNER_RESOLVE_FAILED"])
            else:
                result["inventory_diagnostic"] = _diagnostic("OWNER_RESOLVE_FAILED")
        return result

    def _refusal(self, operation: str, key: str | None, code: str) -> dict[str, Any]:
        return self._result(
            "refused",
            error_code=code,
            mutation={
                "operation": operation, "key": key,
                "commit_state": "not-committed", "application_state": "failed",
                "changed_keys": [], "error_code": code, "message": _MESSAGES[code],
            },
        )

    def _target(self, operation: str, requested: str
                ) -> tuple[SettingSpec | None, dict[str, Any] | None]:
        spec = self._by_key.get(requested)
        if spec is None:
            return None, self._refusal(operation, None, "UNKNOWN_SETTING")
        if spec.value_kind == "opaque":
            return None, self._refusal(operation, spec.key, "OPAQUE_SETTING")
        if spec.caller_mutability == "immutable":
            return None, self._refusal(operation, spec.key, "IMMUTABLE_SETTING")
        if spec.caller_mutability == "owner-only":
            return None, self._refusal(operation, spec.key, "OWNER_ONLY_SETTING")
        return spec, None

    def __call__(self, action_input: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(action_input, Mapping):
            return self._refusal("set", None, "INVALID_INPUT")
        keys = set(action_input)
        if not keys:
            return self._result("ok")
        if keys == {"set", "value"} and isinstance(action_input.get("set"), str):
            operation = "set"
            requested = action_input["set"]
            spec, refusal = self._target(operation, requested)
            if refusal is not None:
                return refusal
            assert spec is not None
            try:
                value = normalize_setting_value(spec.value_kind, action_input["value"])
                value = list(value) if isinstance(value, tuple) else value
            except (TypeError, ValueError):
                return self._refusal(operation, spec.key, "INVALID_VALUE")
            return self._invoke(spec, operation, lambda: self._owner.set(spec, value))
        if keys == {"reset"} and isinstance(action_input.get("reset"), str):
            operation = "reset"
            requested = action_input["reset"]
            spec, refusal = self._target(operation, requested)
            if refusal is not None:
                return refusal
            assert spec is not None
            return self._invoke(spec, operation, lambda: self._owner.reset(spec))
        operation = "set" if "set" in keys else "reset"
        return self._refusal(operation, None, "INVALID_INPUT")

    def _invoke(
        self, spec: SettingSpec, operation: str, call: Any
    ) -> dict[str, Any]:
        try:
            receipt = call()
        except Exception:
            return self._unknown(spec, operation, "OWNER_MUTATION_UNKNOWN")
        projected = self._project_receipt(spec, operation, receipt)
        if projected is None:
            return self._unknown(spec, operation, "INVALID_OWNER_RESULT")
        status, error_code, payload = projected
        return self._result(status, error_code=error_code, mutation=payload)

    def _unknown(self, spec: SettingSpec, operation: str, code: str) -> dict[str, Any]:
        payload = {
            "operation": operation, "key": spec.key, "commit_state": "unknown",
            "application_state": "unknown", "changed_keys": [], "error_code": code,
            "message": _MESSAGES[code],
        }
        return self._result("unknown", error_code=code, mutation=payload)

    def _project_receipt(
        self, spec: SettingSpec, operation: str, receipt: Any
    ) -> tuple[str, str | None, dict[str, Any]] | None:
        """Validate and project an owner result without trusting post-init state."""
        try:
            if type(receipt) is not SettingMutationReceipt:
                return None
            SettingMutationReceipt.__post_init__(receipt)
            if receipt.operation != operation or receipt.key != spec.key:
                return None
            if any(key not in self._by_key for key in receipt.changed_keys):
                return None
            if receipt.commit_state == "committed":
                if spec.key not in receipt.changed_keys:
                    return None
                allowed_application = (
                    {"applied", "failed", "unknown"}
                    if spec.application_timing == "live-now"
                    else {"pending", "failed", "unknown"}
                )
                if receipt.application_state not in allowed_application:
                    return None
            elif receipt.commit_state == "not-committed":
                if receipt.error_code not in {"INVALID_VALUE", "SETTING_UNAVAILABLE"}:
                    return None
            elif receipt.error_code != "OWNER_MUTATION_UNKNOWN":
                return None

            payload = {
                "operation": receipt.operation,
                "key": receipt.key,
                "commit_state": receipt.commit_state,
                "application_state": receipt.application_state,
                "changed_keys": list(receipt.changed_keys),
            }
            if receipt.error_code is not None:
                payload.update(
                    error_code=receipt.error_code,
                    message=_MESSAGES[receipt.error_code],
                )
            status = {
                "not-committed": "refused",
                "committed": "committed",
                "unknown": "unknown",
            }[receipt.commit_state]
            return status, receipt.error_code, payload
        except Exception:
            return None


def build_settings_child(contract: ToolSettingsContract,
                         owner: SettingOwner | None) -> ChildTool:
    """Build the actual child whose controller carries the contract identity."""
    if not isinstance(contract, ToolSettingsContract):
        raise ValueError("settings must be a ToolSettingsContract")
    if owner is not None:
        missing = [
            name for name in ("resolve", "set", "reset")
            if not callable(getattr(owner, name, None))
        ]
        if missing:
            raise ValueError(
                "settings owner must provide callable resolve, set, and reset; "
                f"missing {missing}"
            )
    if owner is None and contract.specs:
        raise ValueError("non-empty settings contract requires an owner")
    controller = _SettingsController(contract, owner)
    return ChildTool(name=SETTINGS_ACTION, input_schema=settings_input_schema(),
                     handler=controller, title="settings input")

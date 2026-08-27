"""Focused synthetic proofs for the opt-in ToolPlugin settings contract."""
from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest

from lingtai.kernel.tool_plugin import (
    BoundToolPlugin,
    OFFICIAL_TOOL_PLUGIN_NAMES,
    ToolPluginDeclaration,
    ToolPluginDeclarationError,
    ToolPluginHost,
)
from lingtai.kernel.tool_plugin.settings import (
    MAX_CONTRACT_SPECS,
    MAX_INTEGER_ABS,
    MAX_METADATA_CHARACTERS,
    MAX_STRING_CHARACTERS,
    MAX_STRING_LIST_ITEMS,
    REDACTED_VALUE,
    SettingMutationReceipt,
    SettingSpec,
    SettingState,
    ToolSettingsContract,
    normalize_setting_value,
    settings_input_schema,
)
from lingtai.mcp_servers.cloud_mail.plugin import CLOUD_MAIL_PLUGIN
from lingtai.mcp_servers.feishu.plugin import FEISHU_PLUGIN
from lingtai.mcp_servers.imap.plugin import IMAP_PLUGIN
from lingtai.mcp_servers.telegram.plugin import TELEGRAM_PLUGIN
from lingtai.mcp_servers.wechat.plugin import WECHAT_PLUGIN
from lingtai.mcp_servers.whatsapp.plugin import WHATSAPP_PLUGIN
from lingtai.tools.tool_family import ChildTool, ToolFamily, ToolFamilyError

_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
_NO_DEFAULT = object()
APPLICATION_APPLIED, APPLICATION_FAILED, APPLICATION_PENDING = "applied", "failed", "pending"
APPLICATION_LIVE_NOW, APPLICATION_NEXT_OPERATION = "live-now", "next-operation"
COMMIT_COMMITTED, COMMIT_NOT_COMMITTED = "committed", "not-committed"
CALLER_MUTABILITY_MUTABLE, CALLER_MUTABILITY_IMMUTABLE = "mutable", "immutable"
CALLER_MUTABILITY_OWNER_ONLY = "owner-only"
SENSITIVITY_PUBLIC, SENSITIVITY_REDACTED = "public", "redacted"
SOURCE_DEFAULT, SOURCE_OWNER = "default", "owner"
VALUE_BOOLEAN, VALUE_INTEGER, VALUE_NUMBER = "boolean", "integer", "number"
VALUE_OPAQUE, VALUE_STRING, VALUE_STRING_LIST = "opaque", "string", "string-list"


def _child(name: str, properties: dict[str, Any] | None = None) -> ChildTool:
    schema = _EMPTY if properties is None else {
        "type": "object", "properties": properties, "additionalProperties": False}
    return ChildTool(name, schema, lambda value: {"status": "ok", "input": dict(value)})


def _spec(
    key: str,
    kind: str = VALUE_STRING,
    *,
    default: Any = _NO_DEFAULT,
    mutability: str = CALLER_MUTABILITY_MUTABLE,
    timing: str = APPLICATION_LIVE_NOW,
    sensitivity: str = SENSITIVITY_PUBLIC,
    env: str | None = None,
) -> SettingSpec:
    precedence = [SOURCE_OWNER]
    if env is not None:
        precedence.append("environment")
    if default is not _NO_DEFAULT:
        precedence.append(SOURCE_DEFAULT)
    fields = dict(key=key, value_kind=kind, env=env,
                  precedence=tuple(precedence),
                  caller_mutability=mutability, application_timing=timing,
                  sensitivity=sensitivity, comment=f"comment:{key}")
    if default is not _NO_DEFAULT:
        fields["default"] = default
    return SettingSpec(**fields)


class _Owner:
    def __init__(self, specs: tuple[SettingSpec, ...]) -> None:
        self.values = {
            spec.key: spec.default_value() if spec.has_default else f"value:{spec.key}"
            for spec in specs
        }
        self.calls: list[tuple[str, str, Any]] = []
        self.receipt: Any = None
        self.raise_after_commit = False
        self.fail_resolve = False

    def resolve(self, spec: SettingSpec) -> SettingState:
        if self.fail_resolve:
            raise RuntimeError("private resolve detail")
        source = SOURCE_DEFAULT if spec.has_default and self.values[spec.key] == spec.default_value() else SOURCE_OWNER
        return SettingState(True, self.values[spec.key], source)

    def _mutate(self, operation: str, spec: SettingSpec, value: Any) -> Any:
        self.calls.append((operation, spec.key, value))
        if operation == "set":
            self.values[spec.key] = value
        elif spec.has_default:
            self.values[spec.key] = spec.default_value()
        if self.raise_after_commit:
            raise RuntimeError("private mutation detail")
        if self.receipt is not None:
            return self.receipt
        application = (
            APPLICATION_APPLIED
            if spec.application_timing == APPLICATION_LIVE_NOW
            else APPLICATION_PENDING
        )
        return SettingMutationReceipt(operation, spec.key, COMMIT_COMMITTED,
                                      application, (spec.key,))

    def set(self, spec: SettingSpec, value: Any) -> Any:
        return self._mutate("set", spec, value)

    def reset(self, spec: SettingSpec) -> Any:
        return self._mutate("reset", spec, None)


def _family(specs: tuple[SettingSpec, ...], owner: Any | None = None,
            children: list[ChildTool] | None = None) -> ToolFamily:
    return ToolFamily(
        "widget",
        [_child("manual")] if children is None else children,
        settings_contract=ToolSettingsContract(specs),
        settings_owner=owner,
    )


def _settings(family: ToolFamily, value: Any) -> dict[str, Any]:
    return family.handle({"action": "settings", "input": value, "reasoning": "test"})


def _bound(family: ToolFamily) -> BoundToolPlugin:
    return BoundToolPlugin("widget", family.build_schema(), family.handle)


def test_absent_empty_nonempty_order_zero_one_many_and_real_binding_identity():
    absent_family = ToolFamily("widget", [_child("one"), _child("manual")])
    absent = ToolPluginDeclaration(
        "widget", ("one",), {"one": _EMPTY}, _EMPTY, "widget-manual", "absent",
        lambda _host: _bound(absent_family),
    )
    assert absent.settings is None
    assert absent.public_actions == ("one", "manual")
    absent.bind(ToolPluginHost.grant(absent, {}))

    empty = ToolSettingsContract(())
    holder: dict[str, ToolPluginDeclaration] = {}
    opted_in = ToolPluginDeclaration(
        "widget", (), {}, _EMPTY, "widget-manual", "empty",
        lambda _host: _bound(ToolFamily(
            "widget", [_child("manual")], settings_contract=holder["decl"].settings
        )),
        settings=empty,
    )
    holder["decl"] = opted_in
    assert opted_in.public_actions == ("settings", "manual")
    assert _settings(ToolFamily("widget", [], settings_contract=empty), {})["settings"] == []
    opted_in.bind(ToolPluginHost.grant(opted_in, {}))

    specs = (_spec("name", default="a"),)
    owner = _Owner(specs)
    branches = [_child("zero"), _child("one", {"x": {"type": "string"}}),
                _child("manual")]
    many = _family(specs, owner, branches)
    assert many.child_names == ("zero", "one", "settings", "manual")
    assert "anyOf" in many.build_schema()["properties"]["input"]
    no_manual = _family(specs, owner, [_child("one")])
    assert no_manual.child_names == ("one", "settings")
    with pytest.raises(ToolFamilyError, match="at least one child"):
        ToolFamily("widget", [])

    other = ToolSettingsContract(())
    dishonest = replace(
        opted_in,
        binder=lambda _host: _bound(
            ToolFamily("widget", [_child("manual")], settings_contract=other)
        ),
    )
    with pytest.raises(ToolPluginDeclarationError, match="different declaration contract"):
        dishonest.bind(ToolPluginHost.grant(dishonest, {}))

    hidden_contract = ToolSettingsContract(())
    hidden = replace(
        absent,
        binder=lambda _host: _bound(ToolFamily(
            "widget", [_child("one"), _child("manual")],
            settings_contract=hidden_contract,
        )),
    )
    with pytest.raises(ToolPluginDeclarationError, match="different declaration contract"):
        hidden.bind(ToolPluginHost.grant(hidden, {}))

    missing = replace(
        opted_in,
        binder=lambda _host: _bound(ToolFamily("widget", [_child("manual")])),
    )
    with pytest.raises(ToolPluginDeclarationError, match="different declaration contract"):
        missing.bind(ToolPluginHost.grant(missing, {}))


def test_input_is_strict_and_reserved_settings_cannot_be_hand_authored():
    spec = _spec("text", default="default")
    owner = _Owner((spec,))
    family = _family((spec,), owner)
    assert set(settings_input_schema()["properties"]) == {"set", "value", "reset"}
    assert _settings(family, {})["status"] == "ok"
    applied = _settings(family, {"set": "text", "value": "new"})
    assert (applied["status"], applied["mutation"]["application_state"]) == (
        "committed", APPLICATION_APPLIED)
    assert _settings(family, {"reset": "text"})["status"] == "committed"
    handler = family._tool_settings_handler()
    assert handler is not None
    for invalid in ({"set": "text"}, {"reset": "text", "value": 1}, {"extra": 1}):
        assert handler(invalid)["mutation"]["commit_state"] == COMMIT_NOT_COMMITTED
    assert _settings(family, {"extra": 1})["status"] == "failed"
    assert handler([])["error_code"] == "INVALID_INPUT"  # type: ignore[arg-type]
    with pytest.raises(ToolFamilyError, match="reserved child 'settings'"):
        ToolFamily("widget", [_child("settings")], settings_contract=ToolSettingsContract(()))
    with pytest.raises(ToolFamilyError, match="reserved child 'settings'"):
        ToolFamily("widget", [_child("settings")])
    with pytest.raises(ToolFamilyError, match="callable resolve, set, and reset"):
        _family((spec,), object())


def test_closed_value_kinds_bounds_and_nonrecursive_refusal():
    cases = (
        (VALUE_BOOLEAN, True),
        (VALUE_INTEGER, 7),
        (VALUE_NUMBER, 1.5),
        (VALUE_STRING, "text"),
        (VALUE_STRING_LIST, ["a", "b"]),
        (VALUE_OPAQUE, ("inventory",)),
    )
    for index, (kind, value) in enumerate(cases):
        mutability = (CALLER_MUTABILITY_OWNER_ONLY if kind == VALUE_OPAQUE
                      else CALLER_MUTABILITY_MUTABLE)
        spec = _spec(f"kind-{index}", kind, default=value, mutability=mutability)
        assert spec.has_default
        family = _family((spec,), _Owner((spec,)))
        assert _settings(family, {})["status"] == "ok"
        if kind != VALUE_OPAQUE:
            assert _settings(family, {"set": spec.key, "value": value})["status"] == "committed"
    with pytest.raises(ValueError):
        normalize_setting_value(VALUE_INTEGER, True)
    with pytest.raises(ValueError):
        normalize_setting_value(VALUE_NUMBER, float("inf"))
    with pytest.raises(ValueError):
        normalize_setting_value(VALUE_STRING, "x" * (MAX_STRING_CHARACTERS + 1))
    with pytest.raises(ValueError):
        normalize_setting_value(VALUE_STRING, "é" * 8_193)
    with pytest.raises(ValueError):
        normalize_setting_value(VALUE_STRING_LIST, ["x"] * (MAX_STRING_LIST_ITEMS + 1))
    with pytest.raises(ValueError):
        normalize_setting_value(VALUE_STRING_LIST, ["x" * 1_025] * 1_024)
    with pytest.raises(ValueError):
        normalize_setting_value(VALUE_OPAQUE, {"nested": "object"})
    cycle: list[Any] = []
    cycle.append(cycle)
    for invalid in ({"nested": "object"}, [["nested"]], cycle):
        with pytest.raises(ValueError):
            normalize_setting_value(VALUE_STRING_LIST, invalid)
    spec = _spec("items", VALUE_STRING_LIST, default=[])
    result = _settings(_family((spec,), _Owner((spec,))), {"set": "items", "value": cycle})
    assert result["error_code"] == "INVALID_VALUE"
    assert result["mutation"]["commit_state"] == COMMIT_NOT_COMMITTED


def test_numeric_metadata_spec_count_and_precedence_bounds_are_closed():
    for kind in (VALUE_INTEGER, VALUE_NUMBER, VALUE_OPAQUE):
        with pytest.raises(ValueError):
            normalize_setting_value(kind, MAX_INTEGER_ABS + 1)

    with pytest.raises(ValueError):
        _spec("a" * (MAX_METADATA_CHARACTERS + 1))
    with pytest.raises(ValueError):
        _spec("env", env="A" * (MAX_METADATA_CHARACTERS + 1))
    with pytest.raises(ValueError):
        SettingSpec(
            key="comment", value_kind=VALUE_STRING, env=None,
            precedence=(SOURCE_OWNER,), caller_mutability=CALLER_MUTABILITY_MUTABLE,
            application_timing=APPLICATION_LIVE_NOW, sensitivity=SENSITIVITY_PUBLIC,
            comment="x" * (MAX_METADATA_CHARACTERS + 1),
        )
    with pytest.raises(ValueError):
        ToolSettingsContract(tuple(_spec(f"bounded-{index}")
                                   for index in range(MAX_CONTRACT_SPECS + 1)))

    base = dict(
        key="coherent", value_kind=VALUE_STRING,
        caller_mutability=CALLER_MUTABILITY_MUTABLE,
        application_timing=APPLICATION_LIVE_NOW, sensitivity=SENSITIVITY_PUBLIC,
        comment="coherent",
    )
    for fields in (
        dict(env="WIDGET_VALUE", precedence=(SOURCE_OWNER,)),
        dict(env=None, precedence=(SOURCE_OWNER, "environment")),
        dict(env=None, precedence=(SOURCE_OWNER, SOURCE_DEFAULT)),
    ):
        with pytest.raises(ValueError):
            SettingSpec(**base, **fields)
    with pytest.raises(ValueError):
        SettingSpec(**base, env=None, precedence=(SOURCE_OWNER,), default="value")


def test_specs_states_contracts_are_immutable_and_project_detached_values():
    spec = _spec("items", VALUE_STRING_LIST, default=["a"])
    contract = ToolSettingsContract((spec,))
    state = SettingState(True, ["a"], SOURCE_DEFAULT)
    with pytest.raises(FrozenInstanceError):
        spec.comment = "changed"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        state.source = SOURCE_OWNER  # type: ignore[misc]
    first_default = spec.default_value()
    first_default.append("changed")
    assert spec.default_value() == ["a"]
    first_effective = state.effective_value()
    first_effective.append("changed")
    assert state.effective_value() == ["a"]
    assert contract.specs == (spec,)
    with pytest.raises(ValueError):
        SettingState(False)
    with pytest.raises(ValueError):
        SettingState(True, "value", SOURCE_OWNER, "SETTING_UNAVAILABLE")
    with pytest.raises(ValueError):
        SettingMutationReceipt("set", "items", COMMIT_NOT_COMMITTED, APPLICATION_APPLIED)
    with pytest.raises(ValueError):
        SettingMutationReceipt("set", "items", COMMIT_COMMITTED, APPLICATION_FAILED, ("items",))
    with pytest.raises(ValueError):
        SettingMutationReceipt("set", "items", "unknown", APPLICATION_APPLIED)
    integer = _spec("integer", VALUE_INTEGER, default=1)
    bad_owner = _Owner((integer,))
    bad_owner.values["integer"] = "wrong-kind"
    bad_row = _settings(_family((integer,), bad_owner), {})["settings"][0]
    assert bad_row["diagnostic"]["code"] == "OWNER_RESOLVE_FAILED"


def test_public_projection_and_redacted_projection_are_positive_allowlists():
    public = _spec("public", default="visible", env="WIDGET_PUBLIC")
    redacted = _spec("secret", default="private", env="WIDGET_SECRET",
                     sensitivity=SENSITIVITY_REDACTED)
    owner = _Owner((public, redacted))
    rows = _settings(_family((public, redacted), owner), {})["settings"]
    assert rows[0]["effective"] == rows[0]["default"] == "visible"
    assert rows[0]["env"] == "WIDGET_PUBLIC"
    assert rows[0]["comment"] == "comment:public"
    assert rows[1] == {
        "key": "secret",
        "available": True,
        "caller_mutability": "mutable",
        "application_timing": "live-now",
        "sensitivity": "redacted",
        "diagnostic": None,
        "effective": REDACTED_VALUE,
        "default": REDACTED_VALUE,
    }


def test_mutability_opaque_and_all_pre_owner_refusals_are_not_committed():
    specs = (
        _spec("mutable", default="x"),
        _spec("immutable", default="x", mutability=CALLER_MUTABILITY_IMMUTABLE),
        _spec("owner-only", default="x", mutability=CALLER_MUTABILITY_OWNER_ONLY),
        _spec("opaque", VALUE_OPAQUE, default="x", mutability=CALLER_MUTABILITY_IMMUTABLE),
    )
    owner = _Owner(specs)
    family = _family(specs, owner)
    for key, code in (
        ("missing", "UNKNOWN_SETTING"),
        ("immutable", "IMMUTABLE_SETTING"),
        ("owner-only", "OWNER_ONLY_SETTING"),
        ("opaque", "OPAQUE_SETTING"),
    ):
        result = _settings(family, {"set": key, "value": "blocked"})
        assert result["error_code"] == code
        assert result["mutation"]["commit_state"] == COMMIT_NOT_COMMITTED
    assert owner.calls == []


def test_commit_then_raise_and_malformed_receipt_make_commit_unknown_without_leaks():
    spec = _spec("text", default="old")
    owner = _Owner((spec,))
    owner.raise_after_commit = True
    raised = _settings(_family((spec,), owner), {"set": "text", "value": "new"})
    assert raised["mutation"]["commit_state"] == "unknown"
    assert raised["mutation"]["application_state"] == "unknown"
    assert "private" not in repr(raised)
    owner.raise_after_commit = False
    owner.receipt = {"committed": False}
    malformed = _settings(_family((spec,), owner), {"reset": "text"})
    assert malformed["error_code"] == "INVALID_OWNER_RESULT"
    assert malformed["mutation"]["commit_state"] == "unknown"
    owner.receipt = SettingMutationReceipt(
        "set", "text", COMMIT_NOT_COMMITTED, APPLICATION_FAILED, (), "INVALID_VALUE")
    refused = _settings(_family((spec,), owner), {"set": "text", "value": "valid-kind"})
    assert refused["status"] == "refused"
    assert refused["mutation"]["commit_state"] == COMMIT_NOT_COMMITTED


def test_post_owner_receipt_projection_is_total_and_cross_field_closed():
    spec = _spec("text", default="old")
    owner = _Owner((spec,))
    family = _family((spec,), owner)

    corrupted = SettingMutationReceipt(
        "set", "text", COMMIT_COMMITTED, APPLICATION_APPLIED, ("text",))
    object.__setattr__(corrupted, "changed_keys", ["text"])
    owner.receipt = corrupted
    result = _settings(family, {"set": "text", "value": "new"})
    assert result["error_code"] == "INVALID_OWNER_RESULT"
    assert result["mutation"]["commit_state"] == "unknown"

    owner.receipt = SettingMutationReceipt(
        "set", "text", COMMIT_NOT_COMMITTED, APPLICATION_FAILED, (),
        "IMMUTABLE_SETTING")
    result = _settings(family, {"set": "text", "value": "new"})
    assert result["error_code"] == "INVALID_OWNER_RESULT"
    assert result["mutation"]["commit_state"] == "unknown"

    owner.receipt = SettingMutationReceipt(
        "set", "text", "unknown", "unknown", (), "OWNER_MUTATION_UNKNOWN")
    result = _settings(family, {"set": "text", "value": "new"})
    assert result["error_code"] == "OWNER_MUTATION_UNKNOWN"
    assert result["mutation"]["commit_state"] == "unknown"


def test_pending_failed_and_post_resolve_failure_preserve_commit_truth():
    pending_spec = _spec("later", default="old", timing=APPLICATION_NEXT_OPERATION)
    pending_owner = _Owner((pending_spec,))
    pending = _settings(_family((pending_spec,), pending_owner), {"set": "later", "value": "new"})
    assert pending["mutation"]["commit_state"] == COMMIT_COMMITTED
    assert pending["mutation"]["application_state"] == APPLICATION_PENDING

    live = _spec("live", default="old")
    failed_owner = _Owner((live,))
    failed_owner.receipt = SettingMutationReceipt(
        "set", "live", COMMIT_COMMITTED, APPLICATION_FAILED, ("live",),
        "APPLICATION_FAILED")
    failed_owner.fail_resolve = True
    failed = _settings(_family((live,), failed_owner), {"set": "live", "value": "new"})
    assert failed["mutation"]["commit_state"] == COMMIT_COMMITTED
    assert failed["mutation"]["application_state"] == APPLICATION_FAILED
    assert failed["inventory_diagnostic"]["code"] == "OWNER_RESOLVE_FAILED"


@pytest.mark.parametrize(
    "receipt",
    [
        SettingMutationReceipt("reset", "text", COMMIT_COMMITTED, APPLICATION_APPLIED, ("text",)),
        SettingMutationReceipt("set", "other", COMMIT_COMMITTED, APPLICATION_APPLIED, ("other",)),
        SettingMutationReceipt("set", "text", COMMIT_COMMITTED, APPLICATION_APPLIED, ("other",)),
        SettingMutationReceipt("set", "text", COMMIT_COMMITTED, APPLICATION_PENDING, ("text",)),
    ],
)
def test_owner_receipt_operation_key_changed_declaration_and_timing_are_cross_validated(
    receipt,
):
    specs = (_spec("text", default="old"), _spec("other", default="other"))
    owner = _Owner(specs)
    owner.receipt = receipt
    result = _settings(_family(specs, owner), {"set": "text", "value": "new"})
    assert result["error_code"] == "INVALID_OWNER_RESULT"
    assert result["mutation"]["commit_state"] == "unknown"

def test_generic_curated_seam_and_every_packaged_descriptor_remain_opted_out():
    packaged = (TELEGRAM_PLUGIN, IMAP_PLUGIN, FEISHU_PLUGIN,
                WECHAT_PLUGIN, WHATSAPP_PLUGIN, CLOUD_MAIL_PLUGIN)
    assert all(plugin.settings is None and "settings" not in plugin.actions(("probe",)) for plugin in packaged)
    contract = ToolSettingsContract(())
    enabled = replace(TELEGRAM_PLUGIN, settings=contract)
    assert enabled.actions(("probe",)) == ("probe", "settings", "manual")
    assert enabled.build_family([_child("probe")]).child_names == ("probe", "settings", "manual")


def test_every_official_toolplugin_and_psyche_root_remain_opted_out():
    module_by_name = {
        "shell": "bash._tool_family",
        "web": "web_search",
    }
    seen = set()
    for name in OFFICIAL_TOOL_PLUGIN_NAMES:
        module_name = module_by_name.get(name, name)
        declaration = importlib.import_module(f"lingtai.tools.{module_name}").DECLARATION
        assert declaration.name == name
        assert declaration.settings is None
        assert "settings" not in declaration.public_actions
        seen.add(name)
    assert seen == set(OFFICIAL_TOOL_PLUGIN_NAMES)

    psyche = importlib.import_module("lingtai.tools.psyche")
    assert "settings" not in psyche.get_schema()["properties"]["action"]["enum"]

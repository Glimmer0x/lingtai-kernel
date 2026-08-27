"""Focused synthetic proofs for the opt-in ToolPlugin settings contract."""
from __future__ import annotations

import importlib
import json
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
    MAX_PRECEDENCE_ENTRIES,
    MAX_SETTINGS_RESPONSE_BYTES,
    MAX_STRING_CHARACTERS,
    MAX_STRING_LIST_ITEMS,
    REDACTED_VALUE,
    SETTINGS_RESPONSE_TOO_LARGE,
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
APPLICATION_LIVE_NOW, APPLICATION_NEXT_OPERATION = "live-now", "next-operation"
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
    configurable: bool = True,
    timing: str = APPLICATION_LIVE_NOW,
    sensitivity: str = SENSITIVITY_PUBLIC,
    env: str | None = None,
    manual_ref: str | None = None,
) -> SettingSpec:
    precedence = [SOURCE_OWNER]
    if env is not None:
        precedence.append("environment")
    if default is not _NO_DEFAULT:
        precedence.append(SOURCE_DEFAULT)
    fields = dict(
        key=key,
        value_kind=kind,
        configurable=configurable,
        env=env,
        precedence=tuple(precedence),
        application_timing=timing if configurable else None,
        sensitivity=sensitivity,
        manual_ref=manual_ref or f"widget-manual#{key}",
    )
    if default is not _NO_DEFAULT:
        fields["default"] = default
    return SettingSpec(**fields)


class _Owner:
    def __init__(self, specs: tuple[SettingSpec, ...]) -> None:
        self.values = {
            spec.key: spec.default_value() if spec.has_default else f"value:{spec.key}"
            for spec in specs
        }
        self.calls: list[str] = []
        self.fail_resolve = False
        self.unavailable: set[str] = set()

    def resolve(self, spec: SettingSpec) -> SettingState:
        self.calls.append(spec.key)
        if self.fail_resolve:
            raise RuntimeError("private resolve detail")
        if spec.key in self.unavailable:
            return SettingState(False, diagnostic_code="SETTING_UNAVAILABLE")
        source = SOURCE_DEFAULT if spec.has_default and self.values[spec.key] == spec.default_value() else SOURCE_OWNER
        return SettingState(True, self.values[spec.key], source)


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
    assert settings_input_schema() == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }
    assert _settings(family, {})["status"] == "ok"
    handler = family._tool_settings_handler()
    assert handler is not None
    for invalid in (
        {"set": "text"},
        {"set": "text", "value": "new"},
        {"reset": "text"},
        {"extra": 1},
    ):
        assert handler(invalid)["error_code"] == "INVALID_INPUT"
        assert _settings(family, invalid)["error_code"] == "INVALID_ARGUMENT"
    assert handler([])["error_code"] == "INVALID_INPUT"  # type: ignore[arg-type]
    assert owner.values["text"] == "default"
    with pytest.raises(ToolFamilyError, match="reserved child 'settings'"):
        ToolFamily("widget", [_child("settings")], settings_contract=ToolSettingsContract(()))
    with pytest.raises(ToolFamilyError, match="reserved child 'settings'"):
        ToolFamily("widget", [_child("settings")])
    with pytest.raises(ToolFamilyError, match="callable resolve"):
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
        spec = _spec(f"kind-{index}", kind, default=value)
        assert spec.has_default
        family = _family((spec,), _Owner((spec,)))
        row = _settings(family, {})["settings"][0]
        expected = list(value) if isinstance(value, tuple) else value
        assert row["value_kind"] == kind
        assert row["effective"] == expected
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


def test_numeric_metadata_spec_count_and_precedence_bounds_are_closed():
    for kind in (VALUE_INTEGER, VALUE_NUMBER, VALUE_OPAQUE):
        assert normalize_setting_value(kind, -MAX_INTEGER_ABS) == -MAX_INTEGER_ABS
        with pytest.raises(ValueError):
            normalize_setting_value(kind, MAX_INTEGER_ABS + 1)
        with pytest.raises(ValueError):
            normalize_setting_value(kind, -(MAX_INTEGER_ABS + 1))

    with pytest.raises(ValueError):
        _spec("a" * (MAX_METADATA_CHARACTERS + 1))
    with pytest.raises(ValueError):
        _spec("env", env="A" * (MAX_METADATA_CHARACTERS + 1))
    with pytest.raises(ValueError):
        _spec("manual", manual_ref="x" * (MAX_METADATA_CHARACTERS + 1))
    with pytest.raises(ValueError):
        _spec("manual", manual_ref="  ")
    with pytest.raises(ValueError):
        SettingSpec(
            key="source",
            value_kind=VALUE_STRING,
            configurable="yes",  # type: ignore[arg-type]
            env=None,
            precedence=(SOURCE_OWNER,),
            application_timing=APPLICATION_LIVE_NOW,
            sensitivity=SENSITIVITY_PUBLIC,
            manual_ref="widget-manual#source",
        )
    with pytest.raises(ValueError):
        ToolSettingsContract(
            tuple(_spec(f"bounded-{index}") for index in range(MAX_CONTRACT_SPECS + 1))
        )

    base = dict(
        key="coherent",
        value_kind=VALUE_STRING,
        configurable=True,
        env=None,
        application_timing=APPLICATION_LIVE_NOW,
        sensitivity=SENSITIVITY_PUBLIC,
        manual_ref="widget-manual#coherent",
    )
    for precedence in ((), (SOURCE_OWNER, SOURCE_OWNER), ("",)):
        with pytest.raises(ValueError):
            SettingSpec(**base, precedence=precedence)
    with pytest.raises(ValueError):
        SettingSpec(
            **base,
            precedence=tuple(
                f"source-{index}" for index in range(MAX_PRECEDENCE_ENTRIES + 1)
            ),
        )
    with pytest.raises(ValueError):
        SettingSpec(
            **dict(
                base,
                configurable=False,
                application_timing=APPLICATION_LIVE_NOW,
            ),
            precedence=(SOURCE_OWNER,),
        )
    with pytest.raises(ValueError):
        SettingSpec(
            **dict(
                base,
                configurable=False,
                env="WIDGET_VALUE",
                application_timing=None,
            ),
            precedence=(SOURCE_OWNER,),
        )


def test_specs_states_contracts_are_immutable_and_project_detached_values():
    spec = _spec("items", VALUE_STRING_LIST, default=["a"])
    contract = ToolSettingsContract((spec,))
    state = SettingState(True, ["a"], SOURCE_DEFAULT)
    with pytest.raises(FrozenInstanceError):
        spec.manual_ref = "changed"  # type: ignore[misc]
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
    assert rows[0]["manual_ref"] == "widget-manual#public"
    assert rows[1] == {
        "key": "secret",
        "available": True,
        "value_kind": "string",
        "configurable": True,
        "precedence": ["owner", "environment", "default"],
        "application_timing": "live-now",
        "sensitivity": "redacted",
        "manual_ref": "widget-manual#secret",
        "has_default": True,
        "env": "WIDGET_SECRET",
        "source": "default",
        "effective": REDACTED_VALUE,
        "default": REDACTED_VALUE,
    }


def test_show_is_read_only_and_configurable_means_external_owner_route():
    specs = (
        _spec("configurable", default="x", configurable=True),
        _spec("fixed", default="y", configurable=False),
        _spec("opaque", VALUE_OPAQUE, default="inventory", configurable=True),
    )
    owner = _Owner(specs)
    family = _family(specs, owner)
    before = dict(owner.values)
    rows = _settings(family, {})["settings"]
    assert [row["configurable"] for row in rows] == [True, False, True]
    assert "application_timing" not in rows[1]
    assert owner.values == before
    assert owner.calls == [spec.key for spec in specs]

    owner.values["configurable"] = "changed-through-external-owner"
    external_state = dict(owner.values)
    refreshed = _settings(family, {})["settings"]
    assert refreshed[0]["effective"] == "changed-through-external-owner"
    assert owner.values == external_state
    assert owner.calls == [spec.key for spec in specs] * 2

    controller = family._tool_settings_handler()
    assert controller is not None
    assert not hasattr(controller, "set")
    assert not hasattr(controller, "reset")
    assert controller({"set": "configurable", "value": "changed"})[
        "error_code"
    ] == "INVALID_INPUT"
    assert owner.values == external_state


def test_unavailable_and_resolve_failure_diagnostics_are_bounded_and_truthful():
    unavailable = _spec("unavailable", default="fallback", env="WIDGET_VALUE")
    owner = _Owner((unavailable,))
    owner.unavailable.add("unavailable")
    result = _settings(_family((unavailable,), owner), {})
    assert result["status"] == "ok"
    assert result["settings"][0] == {
        "key": "unavailable",
        "available": False,
        "value_kind": "string",
        "configurable": True,
        "precedence": ["owner", "environment", "default"],
        "application_timing": "live-now",
        "sensitivity": "public",
        "manual_ref": "widget-manual#unavailable",
        "has_default": True,
        "env": "WIDGET_VALUE",
        "diagnostic": {
            "code": "SETTING_UNAVAILABLE",
            "message": "setting is currently unavailable",
        },
        "default": "fallback",
    }

    owner.fail_resolve = True
    failed = _settings(_family((unavailable,), owner), {})
    assert failed["status"] == "failed"
    assert failed["error_code"] == "OWNER_RESOLVE_FAILED"
    assert failed["settings"][0]["diagnostic"]["code"] == "OWNER_RESOLVE_FAILED"
    assert "private" not in repr(failed)

    class ExplicitFailureOwner:
        def resolve(self, _spec):
            return SettingState(False, diagnostic_code="OWNER_RESOLVE_FAILED")

    explicit = _settings(_family((unavailable,), ExplicitFailureOwner()), {})
    assert explicit["status"] == "failed"
    assert explicit["error_code"] == "OWNER_RESOLVE_FAILED"


def test_malformed_owner_results_fail_loud_without_leaking_or_fabricating_values():
    spec = _spec("text", default="old")

    class WrongTypeOwner:
        def resolve(self, _spec):
            return {"effective": "private wrong type"}

    class WrongSourceOwner:
        def resolve(self, _spec):
            return SettingState(True, "private wrong source", "undeclared-source")

    for owner in (WrongTypeOwner(), WrongSourceOwner()):
        result = _settings(_family((spec,), owner), {})
        assert result["status"] == "failed"
        assert result["error_code"] == "OWNER_RESOLVE_FAILED"
        row = result["settings"][0]
        assert row["available"] is False
        assert "effective" not in row
        assert row["diagnostic"]["code"] == "OWNER_RESOLVE_FAILED"
        assert "private" not in repr(result)


def test_complete_inventory_has_one_canonical_65536_byte_fail_loud_bound():
    specs = tuple(
        _spec(
            f"large-{index}",
            default="x" * MAX_STRING_CHARACTERS,
            timing=APPLICATION_NEXT_OPERATION,
        )
        for index in range(4)
    )
    owner = _Owner(specs)
    result = _settings(_family(specs, owner), {})
    assert len(owner.calls) < len(specs)
    assert result == {
        "status": "failed",
        "error_code": SETTINGS_RESPONSE_TOO_LARGE,
        "message": "complete settings inventory exceeds the 65536-byte canonical JSON bound",
        "max_bytes": MAX_SETTINGS_RESPONSE_BYTES,
    }
    assert "settings" not in result
    serialized = json.dumps(
        result,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert len(serialized) < MAX_SETTINGS_RESPONSE_BYTES
    assert "x" * 32 not in repr(result)


def test_owner_authoring_types_share_one_public_export_surface():
    module = importlib.import_module("lingtai.kernel.tool_plugin")
    assert module.SettingOwner is not None
    assert module.SettingSpec is SettingSpec
    assert module.SettingState is SettingState
    assert module.ToolSettingsContract is ToolSettingsContract
    assert not hasattr(module, "SettingMutationReceipt")


def test_generic_curated_seam_and_every_packaged_descriptor_remain_opted_out():
    packaged = (TELEGRAM_PLUGIN, IMAP_PLUGIN, FEISHU_PLUGIN,
                WECHAT_PLUGIN, WHATSAPP_PLUGIN, CLOUD_MAIL_PLUGIN)
    assert all(
        plugin.settings is None and "settings" not in plugin.actions(("probe",))
        for plugin in packaged
    )
    contract = ToolSettingsContract(())
    enabled = replace(TELEGRAM_PLUGIN, settings=contract)
    assert enabled.actions(("probe",)) == ("probe", "settings", "manual")
    assert enabled.build_family([_child("probe")]).child_names == (
        "probe", "settings", "manual"
    )


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

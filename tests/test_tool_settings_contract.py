"""Minimal proofs for opt-in, SHOW-only tool settings discovery."""
from __future__ import annotations

import importlib
from dataclasses import replace
from typing import Any

import pytest

from lingtai.kernel.tool_plugin import (BoundToolPlugin, OFFICIAL_TOOL_PLUGIN_NAMES,
    ToolPluginDeclaration, ToolPluginDeclarationError, ToolPluginHost)
from lingtai.tools import tool_family as public_family
from lingtai.tools.tool_family import ChildTool, SettingRow, ToolFamily
from lingtai.tools.tool_family import settings as settings_module

_EMPTY = {"type": "object", "properties": {}, "additionalProperties": False}
_DEFAULT_INPUT = object()


def _child(name: str) -> ChildTool:
    return ChildTool(name, _EMPTY, lambda value: {"status": "ok", "input": dict(value)})


def _family(provider=None) -> ToolFamily:
    return ToolFamily("widget", [_child("probe"), _child("manual")],
                      settings_provider=provider)


def _show(family: ToolFamily, value: Any = _DEFAULT_INPUT) -> dict[str, Any]:
    action_input = {} if value is _DEFAULT_INPUT else value
    return family.handle({"action": "settings", "input": action_input, "reasoning": "test"})


def _bound(family: ToolFamily) -> BoundToolPlugin:
    return BoundToolPlugin("widget", family.build_schema(), family.handle)


def _declaration(enabled: bool, family: ToolFamily) -> ToolPluginDeclaration:
    return ToolPluginDeclaration(
        "widget", ("probe",), {"probe": _EMPTY}, _EMPTY,
        "widget-manual", "test", lambda _host: _bound(family), settings=enabled,
    )


def test_opt_out_opt_in_and_reserved_order():
    plain, opted = _family(), _family(lambda: ())
    assert plain.child_names == ("probe", "manual")
    assert opted.child_names == ("probe", "settings", "manual")
    assert "oneOf" in plain.build_schema()["properties"]["input"]
    assert "anyOf" in opted.build_schema()["properties"]["input"]

    declaration = _declaration(True, opted)
    assert declaration.public_actions == opted.child_names
    assert declaration.public_input_schemas()["settings"] == {**_EMPTY, "required": []}
    declaration.bind(ToolPluginHost.grant(declaration, {}))
    with pytest.raises(ToolPluginDeclarationError, match="advertising"):
        replace(declaration, binder=lambda _host: _bound(plain)).bind(
            ToolPluginHost.grant(declaration, {})
        )

    telegram = importlib.import_module("lingtai.mcp_servers.telegram.plugin").TELEGRAM_PLUGIN
    curated = replace(telegram, settings=True)
    assert curated.actions(("probe",)) == ("probe", "settings", "manual")
    built = curated.build_family([_child("probe")], settings_provider=lambda: ())
    assert built.child_names == curated.actions(("probe",))


@pytest.mark.parametrize("invalid", [None, [], {"set": "x"}, {"reset": True}])
def test_settings_accepts_only_exact_empty_input(invalid):
    calls = 0

    def provider():
        nonlocal calls
        calls += 1
        return ()

    family = _family(provider)
    assert _show(family) == {"status": "ok", "settings": []}
    assert _show(family, invalid)["status"] == "failed"
    assert calls == 1


def test_projection_redaction_manual_ref_and_missing_default():
    family = _family(lambda: (
        SettingRow(
            key="public", effective={"mode": None}, source="environment",
            default=None, configurable=True, config_key="WIDGET_MODE",
            application_timing="next call", manual_ref="widget-manual#mode",
        ),
        SettingRow(
            key="secret", effective="current-secret", source="config file",
            default="default-secret", configurable=True,
            config_key="settings/widget.json#secret", application_timing="relaunch",
            manual_ref="widget-manual#secret", sensitive=True,
        ),
        SettingRow(key="fixed", unavailable="not initialized", configurable=False,
                   manual_ref="widget-manual#fixed"),
    ))
    rows = _show(family)["settings"]
    assert rows[0]["effective"] == {"mode": None}
    assert rows[0]["has_default"] is True and rows[0]["default"] is None
    assert rows[1] == {
        "key": "secret", "effective": "<redacted>", "source": "config file",
        "default": "<redacted>", "has_default": True, "configurable": True,
        "config_key": "settings/widget.json#secret", "application_timing": "relaunch",
        "manual_ref": "widget-manual#secret", "sensitive": True,
    }
    assert rows[2]["unavailable"] == "not initialized"
    assert rows[2]["has_default"] is False and "default" not in rows[2]
    assert "current-secret" not in repr(rows) and "default-secret" not in repr(rows)


def _raises():
    raise RuntimeError("private provider exception")


@pytest.mark.parametrize("provider", [
    _raises,
    lambda: [SettingRow("x", False, "manual#x", unavailable="x" * 1_025)],
    lambda: [SettingRow("x", True, "manual#x", effective="private")],
    lambda: [SettingRow(
        "x", False, "manual#x", effective={"not": {"json"}}, source="owner"
    )],
    lambda: [
        SettingRow("ok", False, "manual#ok", unavailable="later"),
        object(),
    ],
])
def test_provider_errors_and_malformed_rows_are_one_fixed_failure(provider):
    assert _show(_family(provider)) == {
        "status": "failed",
        "error_code": "SETTINGS_UNAVAILABLE",
        "message": "settings inventory is unavailable",
    }


def test_complete_response_bound_stops_provider_without_partial_rows():
    consumed = 0

    def provider():
        nonlocal consumed
        for index in range(10):
            consumed += 1
            yield SettingRow(
                f"large-{index}", False, "widget-manual#large",
                effective="x" * 40_000, source="owner",
            )

    result = _show(_family(provider))
    assert consumed == 2
    assert result == {
        "status": "failed",
        "error_code": "SETTINGS_RESPONSE_TOO_LARGE",
        "message": "settings inventory exceeds the 65536-byte response limit",
        "max_bytes": 65_536,
    }
    assert "settings" not in result


def test_public_export_and_all_production_families_opt_out():
    assert public_family.SettingRow is settings_module.SettingRow is SettingRow
    assert public_family.SettingsProvider is settings_module.SettingsProvider
    kernel = importlib.import_module("lingtai.kernel.tool_plugin")
    assert not hasattr(kernel, "ToolSettingsContract")

    curated = [
        getattr(importlib.import_module(f"lingtai.mcp_servers.{name}.plugin"), f"{name.upper()}_PLUGIN")
        for name in ("telegram", "imap", "feishu", "wechat", "whatsapp", "cloud_mail")
    ]
    assert all(plugin.settings is False for plugin in curated)

    modules = {"shell": "bash._tool_family", "web": "web_search"}
    declarations = [
        importlib.import_module(f"lingtai.tools.{modules.get(name, name)}").DECLARATION
        for name in OFFICIAL_TOOL_PLUGIN_NAMES
    ]
    assert all(item.settings is False and "settings" not in item.public_actions
               for item in declarations)
    psyche = importlib.import_module("lingtai.tools.psyche")
    assert "settings" not in psyche.get_schema()["properties"]["action"]["enum"]

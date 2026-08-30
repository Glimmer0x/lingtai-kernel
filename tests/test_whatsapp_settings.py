"""Focused five-field SHOW proofs for the WhatsApp settings owner."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from lingtai.mcp_servers.whatsapp import client as whatsapp_client
from lingtai.mcp_servers.whatsapp._family import (
    WHATSAPP_ACTIONS,
    WHATSAPP_DECLARED_ACTIONS,
    _whatsapp_input_schemas,
    build_whatsapp_family,
    handle_whatsapp,
)
from lingtai.mcp_servers.whatsapp.manager import WhatsAppManager
from lingtai.mcp_servers.whatsapp.plugin import WHATSAPP_PLUGIN
from lingtai.mcp_servers.whatsapp.server import build_manager
from lingtai.mcp_servers.whatsapp.settings import settings_provider

_KEYS = (
    "config_reference",
    "node_path",
    "bridge_dir",
    "session_dir",
    "store_dir",
    "allowed_wa_ids",
    "autostart",
)
_COMMENTS = (
    "whatsapp-mcp-manual#config-reference",
    "whatsapp-mcp-manual#node-path",
    "whatsapp-mcp-manual#bridge-directory",
    "whatsapp-mcp-manual#session-directory",
    "whatsapp-mcp-manual#message-store-directory",
    "whatsapp-mcp-manual#allowed-whatsapp-ids",
    "whatsapp-mcp-manual#autostart",
)
_FIVE_FIELDS = ("key", "current", "default", "configurable", "comment")
_UNAVAILABLE = {
    "status": "failed",
    "error_code": "SETTINGS_UNAVAILABLE",
    "message": "settings inventory is unavailable",
}


def _manager(tmp_path: Path, **overrides: object) -> WhatsAppManager:
    config: dict[str, object] = {
        "node_path": str(tmp_path / "private-node"),
        "bridge_dir": str(tmp_path / "private-bridge"),
        "session_dir": str(tmp_path / "private-session"),
        "store_dir": str(tmp_path / "private-store"),
        "allowed_wa_ids": ["15551234567"],
        "autostart": False,
    }
    config.update(overrides)
    return WhatsAppManager(
        config,
        working_dir=tmp_path / "private-agent",
        config_path=tmp_path / "private-owner.json",
    )


def _show(manager: WhatsAppManager | None) -> dict[str, object]:
    return handle_whatsapp(
        manager,
        {"action": "settings", "input": {}, "reasoning": "inspect settings"},
    )


def test_provider_has_exact_keys_current_defaults_flags_and_manual_targets(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    rows = tuple(settings_provider(manager)())

    assert tuple(row.key for row in rows) == _KEYS
    assert tuple(row.current for row in rows) == (
        str(tmp_path / "private-owner.json"),
        str(tmp_path / "private-node"),
        str(tmp_path / "private-bridge"),
        str(tmp_path / "private-session"),
        str(tmp_path / "private-store"),
        ["15551234567@c.us"],
        False,
    )
    assert tuple(row.default for row in rows) == (
        None,
        whatsapp_client._default_node(),
        str(whatsapp_client._bridge_dir()),
        str(tmp_path / "private-agent" / ".wwebjs_auth"),
        str(tmp_path / "private-agent" / "whatsapp"),
        None,
        True,
    )
    assert all(row.configurable is True for row in rows)
    assert tuple(row.comment for row in rows) == _COMMENTS
    assert tuple(row._sensitive for row in rows) == (
        True,
        True,
        True,
        True,
        True,
        True,
        False,
    )

    headings = (
        "### CONFIG REFERENCE",
        "### NODE PATH",
        "### BRIDGE DIRECTORY",
        "### SESSION DIRECTORY",
        "### MESSAGE STORE DIRECTORY",
        "### ALLOWED WHATSAPP IDS",
        "### AUTOSTART",
    )
    assert all(heading in WHATSAPP_PLUGIN.skill_body for heading in headings)
    assert "has no set, reset, or mutation API" in WHATSAPP_PLUGIN.skill_body
    assert "verifies with a second SHOW" in WHATSAPP_PLUGIN.skill_body


def test_allowed_wa_ids_row_preserves_none_and_explicit_empty_manager_states(
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path, allowed_wa_ids=None)

    unrestricted = {
        row.key: row for row in settings_provider(manager)()
    }["allowed_wa_ids"]
    assert unrestricted.current is None
    assert unrestricted.default is None

    manager.allowed_wa_ids = set()
    configured_empty = {
        row.key: row for row in settings_provider(manager)()
    }["allowed_wa_ids"]
    assert configured_empty.current == []
    assert configured_empty.default is None


def test_bridge_setting_sections_document_invalid_value_degraded_behavior() -> None:
    body = WHATSAPP_PLUGIN.skill_body
    section_bounds = (
        ("### NODE PATH", "### BRIDGE DIRECTORY"),
        ("### BRIDGE DIRECTORY", "### SESSION DIRECTORY"),
        ("### SESSION DIRECTORY", "### MESSAGE STORE DIRECTORY"),
    )
    for heading, next_heading in section_bounds:
        section = body.split(heading, 1)[1].split(next_heading, 1)[0]
        normalized = " ".join(section.split())
        assert "manager construction" in normalized.lower()
        assert "leaves the MCP in a degraded state" in normalized
        assert (
            "action that needs to start or use the bridge resurfaces the error"
            in normalized
        )


def test_show_projects_ordered_five_fields_and_redacts_private_values(
    tmp_path: Path,
) -> None:
    result = _show(_manager(tmp_path))
    redacted = [
        {
            "key": key,
            "current": "<redacted>",
            "default": "<redacted>",
            "configurable": True,
            "comment": comment,
        }
        for key, comment in zip(_KEYS[:6], _COMMENTS[:6], strict=True)
    ]
    assert result == {
        "settings": [
            *redacted,
            {
                "key": "autostart",
                "current": False,
                "default": True,
                "configurable": True,
                "comment": "whatsapp-mcp-manual#autostart",
            },
        ]
    }
    assert all(tuple(row) == _FIVE_FIELDS for row in result["settings"])
    rendered = repr(result)
    assert all(
        private not in rendered
        for private in (
            str(tmp_path),
            str(whatsapp_client._bridge_dir()),
            "15551234567",
            "LINGTAI_WHATSAPP_CONFIG",
            "LINGTAI_WHATSAPP_SESSION_DIR",
        )
    )


def test_show_uses_applied_startup_snapshot_not_later_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    manager = _manager(tmp_path)
    monkeypatch.setenv("LINGTAI_WHATSAPP_CONFIG", str(tmp_path / "later.json"))
    monkeypatch.setenv("LINGTAI_WHATSAPP_SESSION_DIR", str(tmp_path / "later-session"))
    manager.config["autostart"] = True

    rows = {row.key: row for row in settings_provider(manager)()}
    assert rows["config_reference"].current == str(tmp_path / "private-owner.json")
    assert rows["session_dir"].current == str(tmp_path / "private-session")
    assert rows["autostart"].current is False


def test_unavailable_or_invalid_provider_is_one_fixed_failure_and_show_has_no_writer(
    tmp_path: Path,
) -> None:
    assert _show(None) == _UNAVAILABLE

    manager = _manager(tmp_path)
    before_config = dict(manager.config)
    env_names = ("LINGTAI_WHATSAPP_CONFIG", "LINGTAI_WHATSAPP_SESSION_DIR")
    before_env = {name: os.environ.get(name) for name in env_names}
    before_paths = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    for invalid in ({"set": "autostart", "value": True}, {"reset": "session_dir"}):
        result = handle_whatsapp(
            manager,
            {"action": "settings", "input": invalid, "reasoning": "invalid mutation"},
        )
        assert result["status"] == "failed"
    assert manager.config == before_config
    assert {name: os.environ.get(name) for name in env_names} == before_env
    assert sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*")) == before_paths

    class _Unprintable:
        def __str__(self) -> str:
            raise RuntimeError("private value must not escape")

    manager.bridge.node_path = _Unprintable()
    assert _show(manager) == _UNAVAILABLE


def test_whatsapp_opts_in_and_settings_precedes_manual(tmp_path: Path) -> None:
    assert WHATSAPP_PLUGIN.settings is True
    assert WHATSAPP_ACTIONS == (*WHATSAPP_DECLARED_ACTIONS, "settings", "manual")
    assert _whatsapp_input_schemas()["settings"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }
    assert build_whatsapp_family(_manager(tmp_path)).child_names == WHATSAPP_ACTIONS


def test_config_environment_path_is_current_truth_and_invalid_path_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "whatsapp.json"
    config_path.write_text('{"autostart": false}', encoding="utf-8")
    monkeypatch.setenv("LINGTAI_WHATSAPP_CONFIG", str(config_path))
    manager = build_manager()
    rows = {row.key: row for row in settings_provider(manager)()}
    assert rows["config_reference"].current == str(config_path)
    assert rows["autostart"].current is False

    monkeypatch.setenv("LINGTAI_WHATSAPP_CONFIG", str(tmp_path / "missing.json"))
    with pytest.raises(FileNotFoundError):
        build_manager()


def test_ordinary_send_action_still_dispatches_and_stores(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    class _Bridge:
        alive = True

        def request(self, method, params=None, timeout=30.0):
            assert method == "send"
            return {"id": "sent-1", "wa_id": "15551234567@c.us"}

        def stop(self):
            return None

    manager.bridge = _Bridge()
    result = handle_whatsapp(
        manager,
        {
            "action": "send",
            "input": {"to": "15551234567", "text": "unchanged ordinary action"},
            "reasoning": "non-regression",
        },
    )
    assert result["id"] == "sent-1"
    stored = manager._iter_messages("15551234567@c.us", direction="sent")
    assert [item["body"] for item in stored] == ["unchanged ordinary action"]

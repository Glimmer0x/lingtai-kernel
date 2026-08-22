"""Curated-MCP plugin packaging invariants, proven on the Cloud Mail package.

Adapts ``tests/test_curated_mcp_plugin_package.py``'s Telegram reference-slice
coverage to Cloud Mail, the second package wired through
``lingtai.mcp_servers._plugin.CuratedMcpPlugin``. Cloud Mail's own
``_family.py`` predates ``ToolFamily``/``ChildTool`` and stays a hand-rolled
schema + handler-dict dispatch (``build_cloud_mail_family``/``handle_cloud_mail``);
these tests stay in that shape rather than assuming the Telegram-only
``ToolFamily`` surface (``has_manual()``, ``child_names``).

These tests make no network call and stand up no account: the manual is
account-independent and the family's dispatch boundary rejects every invalid
envelope before any manager I/O.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingtai.mcp_servers import _plugin
from lingtai.mcp_servers._plugin import CuratedMcpPlugin, CuratedMcpPluginError
from lingtai.mcp_servers.cloud_mail import _family
from lingtai.mcp_servers.cloud_mail import manager as cloud_mail_mgr
from lingtai.mcp_servers.cloud_mail import server as cloud_mail_server
from lingtai.mcp_servers.cloud_mail.plugin import (
    CLOUD_MAIL_ACTIONS,
    CLOUD_MAIL_DECLARED_ACTIONS,
    CLOUD_MAIL_PLUGIN,
)
from lingtai.services import mcp_registry
from lingtai.tools.tool_family import ChildTool

_REPO_ROOT = Path(__file__).resolve().parents[1]


class _RecordingManager:
    """Stands in for CloudMailManager; records every flat action it is handed."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def handle(self, args: dict) -> dict:
        self.calls.append(dict(args))
        return {"status": "ok", "action": args.get("action")}


# ---------------------------------------------------------------------------
# The package ships its own MCP declaration
# ---------------------------------------------------------------------------

def test_cloud_mail_package_declaration_matches_the_shipped_curated_catalog_entry():
    """The package owns its launcher; mcp_catalog.json publishes exactly it."""
    catalog = json.loads(
        (_REPO_ROOT / "src/lingtai/mcp_catalog.json").read_text(encoding="utf-8")
    )
    assert catalog["cloud_mail"] == CLOUD_MAIL_PLUGIN.mcp_declaration()


def test_declaration_launches_the_declaring_package_and_validates_as_a_record():
    declaration = CLOUD_MAIL_PLUGIN.mcp_declaration()
    assert declaration["transport"] == "stdio"
    assert declaration["command"] == _plugin.PYTHON_PLACEHOLDER
    assert declaration["args"] == ["-m", "lingtai.mcp_servers.cloud_mail"]
    assert declaration["source"] == _plugin.CURATED_SOURCE
    # The host's registry validator — unchanged — still accepts the record.
    assert mcp_registry.validate_record(declaration) == (True, None)


def test_catalog_loading_is_unchanged_and_still_the_runtime_source():
    """The descriptor documents the record; it does not replace catalog I/O."""
    assert mcp_registry.load_catalog()["cloud_mail"] == CLOUD_MAIL_PLUGIN.mcp_declaration()


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the packaged skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in CLOUD_MAIL_DECLARED_ACTIONS
    assert CLOUD_MAIL_ACTIONS == (*CLOUD_MAIL_DECLARED_ACTIONS, "manual")
    assert CLOUD_MAIL_ACTIONS[-1] == "manual"


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: CLOUD_MAIL_PLUGIN.actions(["check", "manual"]), id="actions"),
        pytest.param(
            lambda: CLOUD_MAIL_PLUGIN.action_input_schemas({"check": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: CLOUD_MAIL_PLUGIN.build_family(
                [
                    ChildTool("check", {"type": "object"}, lambda _i: {}),
                    ChildTool("manual", {"type": "object"}, lambda _i: {"hijacked": True}),
                ]
            ),
            id="family",
        ),
    ],
)
def test_a_package_cannot_declare_re_schema_or_rebind_the_reserved_manual(compose):
    with pytest.raises(CuratedMcpPluginError, match="reserved 'manual'"):
        compose()


def test_composed_actions_and_schema_always_carry_a_strict_empty_manual():
    assert _family.CLOUD_MAIL_ACTIONS == CLOUD_MAIL_ACTIONS
    assert _family._cloud_mail_input_schemas()["manual"] == {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }


def test_manual_answers_from_the_packaged_skill_without_entering_the_manager():
    manager = _RecordingManager()
    result = _family.handle_cloud_mail(
        manager, {"action": "manual", "input": {}, "reasoning": "read the manual"}
    )
    assert manager.calls == []
    assert result == CLOUD_MAIL_PLUGIN.manual_payload()
    assert result["status"] == "ok"
    assert result["action"] == "manual"
    assert result["skill"] == "cloud-mail-mcp-manual"
    skill_path = Path(result["path"])
    assert skill_path.is_absolute() and skill_path.name == "SKILL.md"
    assert result["manual"] == CLOUD_MAIL_PLUGIN.skill_body


def test_manual_payload_is_the_same_document_the_legacy_manager_action_returns():
    """Routing manual through the plugin preserves the existing public result."""
    bare = object.__new__(cloud_mail_mgr.CloudMailManager)
    assert bare._handle_manual() == CLOUD_MAIL_PLUGIN.manual_payload()


def test_manual_still_requires_root_reasoning_like_every_other_action():
    manager = _RecordingManager()
    rejected = _family.handle_cloud_mail(manager, {"action": "manual", "input": {}})
    assert rejected["status"] == "failed"
    assert rejected["error_code"] == "INVALID_ARGUMENT"
    assert rejected["message"] == "reasoning is required"
    # ... and its input stays strictly empty.
    assert _family.handle_cloud_mail(
        manager, {"action": "manual", "input": {"topic": "check"}, "reasoning": "x"}
    )["status"] == "failed"
    assert manager.calls == []


# ---------------------------------------------------------------------------
# The public envelope shape is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_action_family_shape():
    schema = _family.CLOUD_MAIL_SCHEMA
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == list(CLOUD_MAIL_ACTIONS)
    assert "cloud-mail-mcp-manual" in schema["properties"]["action"]["description"]
    branch_titles = [b["title"] for b in schema["properties"]["input"]["anyOf"]]
    assert branch_titles == [f"{action} input" for action in CLOUD_MAIL_ACTIONS]


def test_declared_actions_still_dispatch_flat_into_the_manager():
    manager = _RecordingManager()
    result = _family.handle_cloud_mail(
        manager,
        {"action": "accounts", "input": {}, "reasoning": "probe"},
    )
    assert result["status"] == "ok"
    assert manager.calls == [{"action": "accounts"}]


# ---------------------------------------------------------------------------
# The server advertises the packaged identity, not a hand-copied one
# ---------------------------------------------------------------------------

def test_server_is_named_from_the_plugin_descriptor():
    server = cloud_mail_server.build_server(None)
    assert server.name == CLOUD_MAIL_PLUGIN.server_name == "lingtai-cloud-mail"


def test_server_module_advertises_the_plugin_registry_name():
    assert cloud_mail_server.CLOUD_MAIL_PLUGIN.name == "cloud_mail"


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_package_that_is_not_its_own_module():
    with pytest.raises(CuratedMcpPluginError, match="must be the 'cloud_mail' module"):
        CuratedMcpPlugin(
            name="cloud_mail",
            package="lingtai.mcp_servers.telegram",
            server_name="lingtai-cloud-mail",
            summary="s",
            homepage="h",
            skill_name="cloud-mail-mcp-manual",
        )


def test_descriptor_rejects_a_manual_that_is_not_the_packaged_skill():
    with pytest.raises(CuratedMcpPluginError, match="declares name"):
        CuratedMcpPlugin(
            name="cloud_mail",
            package="lingtai.mcp_servers.cloud_mail",
            server_name="lingtai-cloud-mail",
            summary="s",
            homepage="h",
            skill_name="somebody-elses-manual",
        )


@pytest.mark.parametrize("blank_field", ["name", "package", "server_name", "summary", "homepage", "skill_name"])
def test_descriptor_rejects_blank_identity_fields(blank_field):
    fields = {
        "name": "cloud_mail",
        "package": "lingtai.mcp_servers.cloud_mail",
        "server_name": "lingtai-cloud-mail",
        "summary": "s",
        "homepage": "h",
        "skill_name": "cloud-mail-mcp-manual",
    }
    fields[blank_field] = "  "
    with pytest.raises(CuratedMcpPluginError, match="non-empty string"):
        CuratedMcpPlugin(**fields)

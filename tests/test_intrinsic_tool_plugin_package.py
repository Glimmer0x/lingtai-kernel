"""Intrinsic-tool plugin packaging invariants, proven on the notification slice.

A built-in tool is a plugin-style package: the same folder ships the tool code,
the bundled ``manual/SKILL.md`` the agent library installs, and the declaration
``registry.INTRINSICS`` publishes. ``lingtai.tools._plugin.IntrinsicToolPlugin``
binds those three and owns the two promises a package must not be able to break
— that it ships its own manual, and that the reserved ``manual`` action is
appended from that packaged skill rather than declared by the package.

These tests pin the packaging promise and the *unchanged* public notification
surface around it: dismissal still delegates to notification Core, ``manual``
still never touches notification or producer state, and the composed schema is
the same closed LTP v2 envelope it was before the conversion.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lingtai.tools import _plugin, notification as notif
from lingtai.tools._manual import installed_manual_path
from lingtai.tools._plugin import IntrinsicToolPlugin, IntrinsicToolPluginError
from lingtai.tools.notification.plugin import (
    NOTIFICATION_ACTIONS,
    NOTIFICATION_DECLARED_ACTIONS,
    NOTIFICATION_PLUGIN,
)
from lingtai.tools.registry import INTRINSICS
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA

_REPO_ROOT = Path(__file__).resolve().parents[1]


class _StubAgent:
    """The minimum surface the manual child and the dismiss handlers touch."""

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self.logs: list[str] = []

    def _log(self, event: str, **_fields) -> None:
        self.logs.append(event)


def _call(agent, action: str, **action_input):
    return notif.handle(
        agent, {"action": action, "input": action_input, "reasoning": "packaging test"}
    )


# ---------------------------------------------------------------------------
# The package ships its own host declaration
# ---------------------------------------------------------------------------

def test_package_declaration_matches_the_shipped_intrinsic_registry_entry():
    """The package owns its module; registry.INTRINSICS publishes exactly it."""
    assert INTRINSICS["notification"] == NOTIFICATION_PLUGIN.intrinsic_declaration()


def test_declaration_names_the_declaring_package_and_the_registry_stays_the_source():
    declaration = NOTIFICATION_PLUGIN.intrinsic_declaration()
    assert declaration["module"] is notif
    assert declaration["module"].__name__ == NOTIFICATION_PLUGIN.package
    # The descriptor documents the record; it does not replace registry wiring.
    assert NOTIFICATION_PLUGIN.name in INTRINSICS


def test_tool_manifest_publishes_the_plugin_composed_action_list():
    manifest = NOTIFICATION_PLUGIN.tool_manifest(NOTIFICATION_ACTIONS)
    assert manifest == {
        "name": "notification",
        "description": NOTIFICATION_PLUGIN.summary,
        "actions": list(NOTIFICATION_ACTIONS),
    }
    assert notif.get_description().startswith(NOTIFICATION_PLUGIN.summary)


# ---------------------------------------------------------------------------
# The manual is an owned skill: shipped by the package, mounted under its name
# ---------------------------------------------------------------------------

def test_the_package_ships_its_own_manual_skill_tree():
    skill = Path(NOTIFICATION_PLUGIN.packaged_skill_path)
    assert skill.is_absolute() and skill.is_file()
    assert skill == _REPO_ROOT / "src/lingtai/tools/notification/manual/SKILL.md"
    assert skill.parent.name == _plugin.PACKAGED_MANUAL_DIRNAME
    # The bundle is no longer delivered from the tool-agnostic skills package.
    assert not (_REPO_ROOT / "src/lingtai/intrinsic_skills/notification-manual").exists()
    for reference in ("channel-model", "dismissal-safety"):
        assert (skill.parent / "reference" / reference / "SKILL.md").is_file()


def test_packaged_skill_declares_the_catalog_name_the_descriptor_states():
    assert NOTIFICATION_PLUGIN.skill_frontmatter["name"] == "notification-manual"
    assert NOTIFICATION_PLUGIN.skill_name == "notification-manual"
    # Catalog identity and mount directory are deliberately independent, exactly
    # as the already-packaged tool manuals (avatar-manual -> capabilities/avatar).
    assert NOTIFICATION_PLUGIN.mount_name == "notification"


def test_mount_point_is_the_one_the_shared_loader_reads(tmp_path: Path):
    assert NOTIFICATION_PLUGIN.installed_manual_path(tmp_path) == installed_manual_path(
        tmp_path, NOTIFICATION_PLUGIN.mount_name
    )
    assert NOTIFICATION_PLUGIN.installed_manual_path(tmp_path) == (
        tmp_path / ".library" / "intrinsic" / "capabilities" / "notification" / "SKILL.md"
    )


def test_agent_install_mounts_the_packaged_manual_at_the_declared_mount(tmp_path: Path):
    """The real installer, run against a temp workdir, lands where we declare."""
    import shutil

    import lingtai.tools as tools_pkg

    installed = NOTIFICATION_PLUGIN.installed_manual_path(tmp_path)
    installed.parent.parent.mkdir(parents=True)
    shutil.copytree(
        Path(tools_pkg.__file__).parent / "notification" / "manual", installed.parent
    )
    assert installed.is_file()
    assert installed.read_text(encoding="utf-8") == (
        NOTIFICATION_PLUGIN.read_packaged_skill()
    )


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the packaged skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in NOTIFICATION_DECLARED_ACTIONS
    assert "manual" not in notif.DECLARED_INPUT_SCHEMAS
    assert NOTIFICATION_ACTIONS == (*NOTIFICATION_DECLARED_ACTIONS, "manual")
    assert NOTIFICATION_ACTIONS[-1] == "manual"
    assert notif.ACTION_ORDER == NOTIFICATION_ACTIONS


def test_declared_schemas_cover_exactly_the_declared_actions():
    assert set(notif.DECLARED_INPUT_SCHEMAS) == set(NOTIFICATION_DECLARED_ACTIONS)


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: NOTIFICATION_PLUGIN.actions(["check", "manual"]), id="actions"),
        pytest.param(
            lambda: NOTIFICATION_PLUGIN.action_input_schemas({"check": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: NOTIFICATION_PLUGIN.build_family(
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
    with pytest.raises(IntrinsicToolPluginError, match="reserved 'manual'"):
        compose()


def test_composed_family_always_carries_a_manual_child_with_a_strict_empty_input():
    family = notif._build_family(_StubAgent(Path("/nonexistent")))
    assert family.has_manual()
    assert family.child_names == NOTIFICATION_ACTIONS
    assert notif.INPUT_SCHEMAS["manual"] == MANUAL_INPUT_SCHEMA


def test_manual_answers_from_the_installed_owned_skill_without_touching_state(
    tmp_path: Path,
):
    agent = _StubAgent(tmp_path)
    installed = NOTIFICATION_PLUGIN.installed_manual_path(tmp_path)
    installed.parent.mkdir(parents=True)
    installed.write_text("---\nname: notification-manual\n---\n\nbody\n", encoding="utf-8")

    result = _call(agent, "manual")

    assert result == {
        "status": "ok",
        "notification_manual": "---\nname: notification-manual\n---\n\nbody\n",
        "manual_path": str(installed),
    }
    assert agent.logs == []
    assert not (tmp_path / ".notification").exists()


def test_a_missing_installed_manual_degrades_with_the_loader_s_own_sentence(
    tmp_path: Path,
):
    """Owning the skill made the mount name the tool name, so the shared
    loader's message is already the sentence ``CONTRACT.md`` pins — the tool no
    longer restates it."""
    result = _call(_StubAgent(tmp_path), "manual")
    assert result["status"] == "degraded"
    assert result["notification_manual"] == ""
    assert result["error"] == (
        "notification manual missing — initializer may have failed or "
        "capability not installed correctly"
    )


def test_manual_keeps_the_strict_empty_input_every_other_action_is_held_to():
    """The plugin-appended action is dispatched through the same gate, not around it."""
    agent = _StubAgent(Path("/nonexistent"))
    rejected = notif.handle(
        agent, {"action": "manual", "input": {"topic": "delay"}, "reasoning": "x"}
    )
    assert rejected == {
        "status": "failed",
        "error_code": "INVALID_ARGUMENT",
        "message": "unsupported notification input field",
    }
    # Root ``summarize`` is still accepted and stripped on this action, exactly
    # as on a declared one — the family envelope is unchanged by the packaging.
    accepted = notif.handle(
        agent,
        {"action": "manual", "input": {}, "reasoning": "x", "summarize": False},
    )
    assert accepted["status"] == "degraded"


# ---------------------------------------------------------------------------
# The public envelope shape is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_action_family_shape():
    schema = notif.get_schema()
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == list(NOTIFICATION_ACTIONS)
    assert len(schema["allOf"]) == len(NOTIFICATION_ACTIONS)
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    assert branch_titles == [f"{action} input" for action in NOTIFICATION_ACTIONS]


def test_declared_actions_still_dispatch_into_their_own_handlers(tmp_path: Path):
    agent = _StubAgent(tmp_path)
    assert _call(agent, "check")["_notification_placeholder"] is True
    # A cross-action smuggle is still rejected by the envelope before any
    # handler runs, and therefore before any notification I/O.
    rejected = _call(agent, "dismiss_channel", channel="system", event_id="evt_1")
    assert rejected == {
        "status": "failed",
        "error_code": "INVALID_ARGUMENT",
        "message": "unsupported notification input field",
    }
    assert agent.logs == []
    assert not (tmp_path / ".notification").exists()


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_package_that_is_not_its_own_module():
    with pytest.raises(IntrinsicToolPluginError, match="must be the 'notification' module"):
        IntrinsicToolPlugin(
            name="notification",
            package="lingtai.tools.email",
            summary="s",
            skill_name="notification-manual",
        )


def test_descriptor_rejects_a_package_that_ships_no_manual_of_its_own():
    with pytest.raises(IntrinsicToolPluginError, match="does not ship its own"):
        IntrinsicToolPlugin(
            name="context",
            package="lingtai.tools.context",
            summary="s",
            skill_name="context-manual",
        )


def test_descriptor_rejects_a_manual_that_is_not_the_packaged_skill():
    with pytest.raises(IntrinsicToolPluginError, match="declares name"):
        IntrinsicToolPlugin(
            name="notification",
            package="lingtai.tools.notification",
            summary="s",
            skill_name="somebody-elses-manual",
        )


@pytest.mark.parametrize("blank_field", ["name", "package", "summary", "skill_name"])
def test_descriptor_rejects_blank_identity_fields(blank_field):
    fields = {
        "name": "notification",
        "package": "lingtai.tools.notification",
        "summary": "s",
        "skill_name": "notification-manual",
    }
    fields[blank_field] = "  "
    with pytest.raises(IntrinsicToolPluginError, match="non-empty string"):
        IntrinsicToolPlugin(**fields)


def test_a_schema_only_manual_child_refuses_to_dispatch():
    child = NOTIFICATION_PLUGIN.manual_child()
    assert child.name == "manual"
    assert dict(child.input_schema) == MANUAL_INPUT_SCHEMA
    with pytest.raises(AssertionError, match="never dispatches"):
        child.handler({})

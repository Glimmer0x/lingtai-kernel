"""Intrinsic-tool plugin packaging invariants, proven on the Soul reference slice.

A LingTai-owned tool is a plugin-style package: the same folder ships the tool
code, the bundled ``manual/SKILL.md``, and the two runtime records the host
materializes for it — the ``registry.INTRINSICS`` entry that mounts the family
and the manual mount that installs the packaged skill into
``.library/intrinsic/capabilities/``. ``lingtai.tools._plugin.IntrinsicToolPlugin``
binds those and owns the one promise a package must not be able to break: the
reserved ``manual`` action, appended by the plugin and bound to the package's
own skill rather than declared by the package.

These tests pin the packaging promise, the real discovery/mount round trip
through the host installer, and the *unchanged* public Soul surface around it.
They start no timer, enable no flow, and make no LLM call: the plugin seam is
schema/skill material only, and every dispatch here is ``manual``, which the
contract requires to perform no soul operation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import lingtai.tools as tools_pkg
from lingtai.agent import Agent
from lingtai.tools import _plugin, registry
from lingtai.tools import soul as soul_tool
from lingtai.tools._plugin import (
    IntrinsicToolPlugin,
    IntrinsicToolPluginError,
    discover_intrinsic_plugins,
    intrinsic_manual_mounts,
)
from lingtai.tools.soul.plugin import (
    SOUL_ACTIONS,
    SOUL_DECLARED_ACTIONS,
    SOUL_PLUGIN,
)
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA

_REPO_ROOT = Path(__file__).resolve().parents[1]


class _ManualAgent:
    """The minimum host surface the manual child and the installer touch."""

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self._capabilities: list[tuple[str, dict]] = []


def _install_manuals(working_dir: Path) -> _ManualAgent:
    """Run the real host installer against a bare working directory."""
    agent = _ManualAgent(working_dir)
    Agent._install_intrinsic_manuals(agent)
    return agent


# ---------------------------------------------------------------------------
# The package ships its own runtime records
# ---------------------------------------------------------------------------

def test_soul_package_declaration_matches_the_shipped_intrinsic_registry_entry():
    """The package owns its module; registry.INTRINSICS publishes exactly it."""
    assert registry.INTRINSICS["soul"] == SOUL_PLUGIN.intrinsic_declaration()
    assert registry.INTRINSICS["soul"]["module"] is soul_tool


def test_declaration_mounts_the_declaring_package():
    declaration = SOUL_PLUGIN.intrinsic_declaration()
    assert declaration["module"].__name__ == SOUL_PLUGIN.package == "lingtai.tools.soul"


def test_manual_mount_declaration_states_source_bundle_and_destination():
    assert SOUL_PLUGIN.manual_mount_declaration() == {
        "name": "soul",
        "summary": SOUL_PLUGIN.summary,
        "source": _plugin.INTRINSIC_SOURCE,
        "package": "lingtai.tools.soul",
        "bundle": "soul/manual",
        "skill": "soul-manual",
        "mount": "capabilities/soul-manual",
    }


# ---------------------------------------------------------------------------
# The manual is an owned skill: shipped by the package, not a loose bundle
# ---------------------------------------------------------------------------

def test_the_package_ships_the_skill_it_declares():
    packaged = _REPO_ROOT / "src/lingtai/tools/soul/manual/SKILL.md"
    assert packaged.is_file()
    assert Path(SOUL_PLUGIN.skill_path) == packaged
    assert SOUL_PLUGIN.skill_text == packaged.read_text(encoding="utf-8")
    assert SOUL_PLUGIN.skill_frontmatter["name"] == "soul-manual"
    assert SOUL_PLUGIN.skill_body.lstrip().startswith("# Soul Manual")


def test_the_skill_no_longer_ships_as_a_standalone_bundle():
    """It has a companion tool package now, so it is not an intrinsic_skills bundle."""
    assert not (_REPO_ROOT / "src/lingtai/intrinsic_skills/soul-manual").exists()


# ---------------------------------------------------------------------------
# Runtime discovery and mount: the host asks, the host copies
# ---------------------------------------------------------------------------

def test_discovery_finds_the_declaring_package_keyed_by_its_directory():
    discovered = discover_intrinsic_plugins()
    assert discovered["soul"] is SOUL_PLUGIN
    assert intrinsic_manual_mounts()["soul"] == SOUL_PLUGIN.mount_name == "soul-manual"


def test_discovery_only_reports_packages_that_declare_themselves():
    """A tool package without a plugin.py is scanned and left alone."""
    tools_root = Path(tools_pkg.__file__).resolve().parent
    discovered = discover_intrinsic_plugins()
    for directory in ("email", "system", "context", "notification", "psyche"):
        assert (tools_root / directory).is_dir()
        assert not (tools_root / directory / "plugin.py").exists()
        assert directory not in discovered


def test_the_host_installer_materializes_exactly_the_declared_mount(tmp_path: Path):
    """The declaration is a promise the real install path keeps."""
    _install_manuals(tmp_path)

    intrinsic = tmp_path / ".library" / "intrinsic"
    mount = SOUL_PLUGIN.manual_mount_declaration()["mount"]
    installed = intrinsic / mount / _plugin.SKILL_FILENAME

    assert installed.is_file()
    assert installed.read_text(encoding="utf-8") == SOUL_PLUGIN.skill_text
    # The declared mount name wins over the Python package directory name, so
    # the manual does not silently move out from under the agent.
    assert not (intrinsic / "capabilities" / "soul").exists()


def test_the_installed_manual_is_what_the_manual_action_serves(tmp_path: Path):
    """Discovery -> mount -> dispatch, end to end, with no soul operation run."""
    agent = _install_manuals(tmp_path)

    result = soul_tool.handle(agent, {"action": "manual", "input": {}})

    installed = (
        tmp_path / ".library" / "intrinsic" / "capabilities"
        / SOUL_PLUGIN.mount_name / _plugin.SKILL_FILENAME
    )
    assert result == {
        "status": "ok",
        "manual": SOUL_PLUGIN.skill_text,
        "manual_path": str(installed),
    }


def test_a_missing_install_is_still_reported_truthfully(tmp_path: Path):
    """The plugin binds ``manual`` to the installed copy, degraded shape included."""
    result = soul_tool.handle(_ManualAgent(tmp_path), {"action": "manual", "input": {}})

    assert result["status"] == "degraded"
    assert result["manual"] == ""
    assert result["manual_path"].endswith("soul-manual/SKILL.md")
    assert "manual missing" in result["error"]


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and owned by the plugin
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in SOUL_DECLARED_ACTIONS
    assert SOUL_ACTIONS == (*SOUL_DECLARED_ACTIONS, "manual")
    assert SOUL_ACTIONS[-1] == "manual"


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: SOUL_PLUGIN.actions(["inquiry", "manual"]), id="actions"),
        pytest.param(
            lambda: SOUL_PLUGIN.action_input_schemas({"inquiry": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: SOUL_PLUGIN.build_family(
                None,
                [
                    ChildTool("inquiry", {"type": "object"}, lambda _i: {}),
                    ChildTool("manual", {"type": "object"}, lambda _i: {"hijacked": True}),
                ],
            ),
            id="family",
        ),
    ],
)
def test_a_package_cannot_declare_re_schema_or_rebind_the_reserved_manual(compose):
    with pytest.raises(IntrinsicToolPluginError, match="reserved 'manual'"):
        compose()


def test_composed_family_always_carries_a_manual_child_with_a_strict_empty_input():
    family = soul_tool._build_family(None)
    assert family.has_manual()
    assert family.child_names == SOUL_ACTIONS
    assert soul_tool.ACTION_INPUT_SCHEMAS["manual"] == MANUAL_INPUT_SCHEMA
    assert _plugin.strict_empty_input_schema() == MANUAL_INPUT_SCHEMA
    # A copy, never the shared literal: one family's branch cannot mutate the
    # schema every other family composes from.
    assert _plugin.strict_empty_input_schema() is not MANUAL_INPUT_SCHEMA


def test_declared_registries_must_cover_exactly_the_plugin_declared_actions():
    assert tuple(soul_tool._DECLARED_INPUT_SCHEMAS) == SOUL_DECLARED_ACTIONS
    assert tuple(soul_tool._DECLARED_HANDLERS) == SOUL_DECLARED_ACTIONS


# ---------------------------------------------------------------------------
# The public envelope shape is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_action_family_shape():
    schema = soul_tool.get_schema("en")
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == list(SOUL_ACTIONS)
    assert len(schema["allOf"]) == len(SOUL_ACTIONS)
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    assert branch_titles == [f"{action} input" for action in SOUL_ACTIONS]


def test_flow_config_and_voice_inputs_are_unchanged_by_the_packaging():
    """The plugin composes the family; it does not touch soul's own branches."""
    schemas = soul_tool.ACTION_INPUT_SCHEMAS
    assert schemas["flow"] == {
        "type": "object", "properties": {}, "required": [],
        "additionalProperties": False,
    }
    assert set(schemas["config"]["properties"]) == {
        "delay_seconds", "consultation_past_count",
    }
    assert schemas["config"]["required"] == ["delay_seconds", "consultation_past_count"]
    assert set(schemas["voice"]["properties"]) == {"set", "prompt"}
    assert schemas["voice"]["required"] == ["set", "prompt"]
    # No action or input field anywhere in this family can enable flow: the
    # packaging added no knob, and the env gate stays the operator's alone.
    every_field = {
        field for schema in schemas.values() for field in schema["properties"]
    }
    assert every_field == {
        "inquiry", "delay_seconds", "consultation_past_count", "set", "prompt",
    }


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def _fields(**overrides) -> dict:
    base = {
        "name": "soul",
        "package": "lingtai.tools.soul",
        "summary": "s",
        "skill_name": "soul-manual",
    }
    base.update(overrides)
    return base


def test_descriptor_rejects_a_package_that_is_not_its_own_module():
    with pytest.raises(IntrinsicToolPluginError, match="must be the 'soul' module"):
        IntrinsicToolPlugin(**_fields(package="lingtai.tools.email"))


def test_descriptor_rejects_a_manual_that_is_not_the_packaged_skill():
    with pytest.raises(IntrinsicToolPluginError, match="declares name"):
        IntrinsicToolPlugin(**_fields(skill_name="somebody-elses-manual"))


def test_descriptor_rejects_a_package_that_ships_no_skill():
    with pytest.raises(IntrinsicToolPluginError, match="ships no manual/SKILL.md"):
        IntrinsicToolPlugin(
            **_fields(name="context", package="lingtai.tools.context",
                      skill_name="context-manual")
        )


@pytest.mark.parametrize("blank_field", ["name", "package", "summary", "skill_name"])
def test_descriptor_rejects_blank_identity_fields(blank_field):
    with pytest.raises(IntrinsicToolPluginError, match="non-empty string"):
        IntrinsicToolPlugin(**_fields(**{blank_field: "  "}))


def test_descriptor_rejects_a_mount_that_escapes_the_capability_catalog():
    with pytest.raises(IntrinsicToolPluginError, match="one directory name"):
        IntrinsicToolPlugin(**_fields(mount_name="../../custom"))


def test_mount_name_defaults_to_the_registry_name():
    """A package with nothing to say installs under its own name."""
    plugin = IntrinsicToolPlugin(**_fields())
    assert plugin.mount_name == "soul"
    assert plugin.manual_mount_declaration()["mount"] == "capabilities/soul"

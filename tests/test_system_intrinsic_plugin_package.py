"""Intrinsic plugin packaging invariants, proven on the System slice.

An intrinsic is a plugin-style package: the same folder ships the handlers,
names the kernel-shipped ``SKILL.md`` behind its ``manual`` action, and
declares the mount record ``lingtai.tools.registry`` publishes for it.
``lingtai.tools._plugin.IntrinsicPlugin`` binds those three and owns the two
promises a package must not be able to break — the reserved ``manual`` action
(appended from the plugin's own skill, never declared by the package) and the
existence of that skill (resolved and name-checked at import).

These tests pin the packaging promise, the *real* discovery-and-mount path the
registry now takes, and the *unchanged* public System surface around it. They
stand up no agent and touch no lifecycle: the manual is agent-local and every
dispatch assertion goes through the family's own envelope boundary.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from lingtai.tools import _plugin
from lingtai.tools import soul as soul_tool
from lingtai.tools import system as system_tool
from lingtai.tools._plugin import IntrinsicPlugin, IntrinsicPluginError
from lingtai.tools.registry import INTRINSICS
from lingtai.tools.system import schema as system_schema
from lingtai.tools.system.plugin import (
    SYSTEM_ACTIONS,
    SYSTEM_DECLARED_ACTIONS,
    SYSTEM_PLUGIN,
)
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA

_REPO_ROOT = Path(__file__).resolve().parents[1]

#: The public action inventory, unchanged by packaging. Spelled out here rather
#: than imported so a silent reorder or addition in ``plugin.py`` fails.
_CANONICAL_ACTIONS = (
    "refresh",
    "sleep",
    "lull",
    "interrupt",
    "suspend",
    "cpr",
    "clear",
    "nirvana",
    "presets",
    "name_set",
    "name_nickname",
    "manual",
)


class _StubAgent:
    """The minimal duck type ``load_installed_manual`` needs."""

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir


def _install_manual(workdir: Path, capability: str) -> tuple[str, Path]:
    path = workdir / ".library" / "intrinsic" / "capabilities" / capability / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = f"---\nname: {capability}\n---\n\n# {capability} sentinel\n"
    path.write_text(body, encoding="utf-8")
    return body, path


# ---------------------------------------------------------------------------
# The package ships its own mount declaration, and the registry mounts from it
# ---------------------------------------------------------------------------

def test_system_package_declaration_matches_the_registry_mount():
    """The package owns its identity; ``INTRINSICS`` publishes exactly it."""
    declaration = SYSTEM_PLUGIN.intrinsic_declaration()
    mounted = INTRINSICS[declaration["name"]]["module"]
    assert declaration["name"] == "system"
    assert declaration["module"] == mounted.__name__ == "lingtai.tools.system"
    assert declaration["mount"] == "intrinsic"
    assert declaration["source"] == _plugin.INTRINSIC_SOURCE
    assert declaration["manual_skill"] == "system-manual"


def test_registry_mounts_through_plugin_discovery_not_a_hand_written_literal():
    """``registry.INTRINSICS`` is built by ``mount_intrinsics`` from the modules.

    The record shape stays exactly ``{"module": <module>}`` so
    ``BaseAgent._wire_intrinsics`` is untouched — packaging changed how the
    record is *derived*, not what it is.
    """
    assert INTRINSICS["system"] == {"module": system_tool}
    assert _plugin.plugin_of(system_tool) is SYSTEM_PLUGIN


def test_an_unpackaged_intrinsic_is_still_mounted_unchanged():
    """Packaging is opt-in per package, so adoption can be incremental."""
    assert _plugin.plugin_of(soul_tool) is None
    assert INTRINSICS["soul"] == {"module": soul_tool}


@pytest.mark.parametrize(
    ("attribute", "value", "match"),
    [
        pytest.param("name", "sistema", "declares name", id="name"),
        pytest.param("__name__", "lingtai.tools.impostor", "was mounted from", id="module"),
    ],
)
def test_mount_rejects_a_plugin_whose_identity_disagrees(attribute, value, match):
    """A packaged intrinsic cannot be mounted under a name/module it disowns."""
    if attribute == "name":
        impostor = types.SimpleNamespace(
            __name__="lingtai.tools.system",
            PLUGIN=_replace_plugin_name(value),
        )
    else:
        impostor = types.SimpleNamespace(__name__=value, PLUGIN=SYSTEM_PLUGIN)
    with pytest.raises(IntrinsicPluginError, match=match):
        _plugin.mount_intrinsics({"system": impostor})


def _replace_plugin_name(name: str) -> IntrinsicPlugin:
    return IntrinsicPlugin(
        name=name,
        package=f"lingtai.tools.{name}",
        summary=SYSTEM_PLUGIN.summary,
        homepage=SYSTEM_PLUGIN.homepage,
        skill_name="system-manual",
        skill_package=_plugin.INTRINSIC_SKILLS_PACKAGE,
        skill_dir="system-manual",
    )


def test_a_non_plugin_plugin_attribute_is_a_defect_not_an_opt_out():
    module = types.SimpleNamespace(__name__="lingtai.tools.system", PLUGIN=object())
    with pytest.raises(IntrinsicPluginError, match="must be an IntrinsicPlugin"):
        _plugin.mount_intrinsics({"system": module})


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the plugin's own skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in SYSTEM_DECLARED_ACTIONS
    assert SYSTEM_ACTIONS == (*SYSTEM_DECLARED_ACTIONS, "manual")
    assert SYSTEM_ACTIONS[-1] == "manual"


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: SYSTEM_PLUGIN.actions(["sleep", "manual"]), id="actions"),
        pytest.param(
            lambda: SYSTEM_PLUGIN.action_input_schemas({"sleep": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: SYSTEM_PLUGIN.build_family(
                None,
                [
                    ChildTool("sleep", {"type": "object"}, lambda _i: {}),
                    ChildTool("manual", {"type": "object"}, lambda _i: {"hijacked": True}),
                ],
            ),
            id="family",
        ),
    ],
)
def test_a_package_cannot_declare_re_schema_or_rebind_the_reserved_manual(compose):
    with pytest.raises(IntrinsicPluginError, match="reserved 'manual'"):
        compose()


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: SYSTEM_PLUGIN.actions([]), id="actions"),
        pytest.param(lambda: SYSTEM_PLUGIN.action_input_schemas({}), id="schemas"),
        pytest.param(lambda: SYSTEM_PLUGIN.build_family(None, []), id="family"),
    ],
)
def test_a_package_must_declare_at_least_one_action_of_its_own(compose):
    with pytest.raises(IntrinsicPluginError, match="at least one action"):
        compose()


def test_a_package_cannot_declare_a_duplicate_action():
    with pytest.raises(IntrinsicPluginError, match="duplicate action"):
        SYSTEM_PLUGIN.actions(["sleep", "sleep"])


def test_composed_family_always_carries_a_manual_child_with_a_strict_empty_input():
    family = system_tool._FAMILY
    assert family.has_manual()
    assert family.child_names == SYSTEM_ACTIONS
    assert system_schema.INPUT_SCHEMAS["manual"] is MANUAL_INPUT_SCHEMA


def test_manual_is_bound_to_the_plugins_own_skill_and_not_to_an_action_handler(
    tmp_path: Path,
):
    """``manual`` answers from the capability the descriptor names, verbatim.

    The child is the plugin's, so no change to ``_ACTION_HANDLERS`` can drop or
    replace it, and the public flat result shape is unchanged.
    """
    assert "manual" not in system_tool._ACTION_HANDLERS
    body, path = _install_manual(tmp_path, SYSTEM_PLUGIN.installed_capability)
    result = system_tool.handle(
        _StubAgent(tmp_path), {"action": "manual", "input": {}, "reasoning": "read"}
    )
    assert result == {"status": "ok", "manual": body, "manual_path": str(path)}


def test_manual_still_degrades_truthfully_when_the_library_copy_is_missing(
    tmp_path: Path,
):
    """Packaging did not add a fallback to the shipped copy — behavior is pinned."""
    result = system_tool.handle(
        _StubAgent(tmp_path), {"action": "manual", "input": {}, "reasoning": "read"}
    )
    assert result["status"] == "degraded"
    assert result["manual"] == ""
    assert "system-manual manual missing" in result["error"]


# ---------------------------------------------------------------------------
# The declared skill is resolved and validated at import
# ---------------------------------------------------------------------------

def test_the_shipped_skill_is_resolved_and_name_checked_at_construction():
    assert SYSTEM_PLUGIN.skill_frontmatter["name"] == "system-manual"
    assert SYSTEM_PLUGIN.skill_body.strip()
    assert Path(SYSTEM_PLUGIN.skill_source_path) == (
        _REPO_ROOT / "src/lingtai/intrinsic_skills/system-manual/SKILL.md"
    )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        pytest.param({"skill_name": "not-the-system-manual"}, "expected", id="renamed"),
        pytest.param({"skill_dir": "no-such-bundle"}, "unreadable", id="missing"),
        pytest.param({"package": "lingtai.tools.context"}, "must be the", id="wrong-module"),
        pytest.param({"summary": "  "}, "non-empty string", id="blank-field"),
    ],
)
def test_a_broken_descriptor_fails_loudly_at_construction(kwargs, match):
    declared = {
        "name": "system",
        "package": "lingtai.tools.system",
        "summary": SYSTEM_PLUGIN.summary,
        "homepage": SYSTEM_PLUGIN.homepage,
        "skill_name": "system-manual",
        "skill_package": _plugin.INTRINSIC_SKILLS_PACKAGE,
        "skill_dir": "system-manual",
        **kwargs,
    }
    with pytest.raises(IntrinsicPluginError, match=match):
        IntrinsicPlugin(**declared)


# ---------------------------------------------------------------------------
# The derived install destination matches the boot installer's own two passes
# ---------------------------------------------------------------------------

def test_a_standalone_bundle_installs_under_its_own_directory_name():
    """``install_skills_from`` copies ``intrinsic_skills/<entry>`` verbatim."""
    assert SYSTEM_PLUGIN.installed_capability == "system-manual"
    assert (
        _REPO_ROOT / "src/lingtai/intrinsic_skills" / SYSTEM_PLUGIN.installed_capability
    ).is_dir()


def test_a_package_owned_manual_installs_under_the_tool_name():
    """``install_from`` maps ``<pkg>/manual/`` → ``capabilities/<pkg>``.

    Proven against a real package-owned manual (``email``) so the descriptor's
    derivation is checked against the installer's other pass, not just its own.
    """
    email_plugin = IntrinsicPlugin(
        name="email",
        package="lingtai.tools.email",
        summary="LingTai email protocol.",
        homepage=SYSTEM_PLUGIN.homepage,
        skill_name="email-manual",
    )
    assert email_plugin.installed_capability == "email"
    assert Path(email_plugin.skill_source_path) == (
        _REPO_ROOT / "src/lingtai/tools/email/manual/SKILL.md"
    )


# ---------------------------------------------------------------------------
# The public System surface is unchanged
# ---------------------------------------------------------------------------

def test_public_action_inventory_and_order_are_unchanged():
    assert system_schema.ACTION_ORDER == _CANONICAL_ACTIONS
    assert system_tool._FAMILY.child_names == _CANONICAL_ACTIONS
    assert system_tool.get_schema()["properties"]["action"]["enum"] == list(
        _CANONICAL_ACTIONS
    )


def test_action_order_and_input_registry_are_composed_by_the_plugin():
    assert system_schema.ACTION_ORDER is SYSTEM_ACTIONS
    assert set(system_schema.INPUT_SCHEMAS) == set(_CANONICAL_ACTIONS)
    # The declared schema objects are carried through by reference, not copied,
    # so the family's children and this registry cannot hold two versions.
    assert (
        system_schema.INPUT_SCHEMAS["refresh"]
        is system_schema._DECLARED_INPUT_SCHEMAS["refresh"]
    )
    assert "manual" not in system_schema._DECLARED_INPUT_SCHEMAS


def test_root_envelope_and_unknown_action_error_are_unchanged():
    schema = system_tool.get_schema()
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["additionalProperties"] is False
    assert system_tool.handle(None, {"action": "summarize", "input": {}}) == {
        "status": "error",
        "message": "Unknown system action: summarize",
    }

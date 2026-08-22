"""Intrinsic-tool plugin packaging invariants, proven on the Context reference slice.

A model-facing LingTai tool is a plugin-style package: the same folder ships the
tool code, the bundled ``manual/`` skill the agent installs and reads, and the
registration record the built-in registry publishes.
``lingtai.tools._plugin.IntrinsicToolPlugin`` binds those three and owns the one
promise a package must not be able to break — the reserved ``manual`` action,
appended from the packaged bundle rather than declared by the package.

These tests pin the packaging promise, the real discovery/mount path that puts
the packaged bundle into an agent's working directory, and the *unchanged*
public Context surface around all of it. They touch only ``tmp_path``: no agent
is booted, no provider is contacted, and no summarize/molt engine runs.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lingtai.agent import Agent
from lingtai.tools import _plugin
from lingtai.tools import context as context_tool
from lingtai.tools import registry
from lingtai.tools._plugin import IntrinsicToolPlugin, IntrinsicToolPluginError
from lingtai.tools.context.plugin import (
    CONTEXT_ACTIONS,
    CONTEXT_DECLARED_ACTIONS,
    CONTEXT_PLUGIN,
)
from lingtai.tools.tool_family import ChildTool

_REPO_ROOT = Path(__file__).resolve().parents[1]

_DESCRIPTOR_FIELDS = {
    "name": "context",
    "package": "lingtai.tools.context",
    "summary": "s",
    "homepage": "h",
    "skill_name": "context-manual",
}


class _StubAgent:
    """The minimal duck type the reserved ``manual`` child reads."""

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir


def _install_manuals(workdir: Path) -> None:
    """Run the real host installer against a throwaway working directory.

    ``object.__new__`` gives the unbound method its two attributes without
    booting an agent: an empty capability list keeps the ``skills`` reconcile
    branch (and therefore every service, provider, and lock) out of the test.
    """
    host = object.__new__(Agent)
    host._working_dir = workdir
    host._capabilities = []
    Agent._install_intrinsic_manuals(host)


# ---------------------------------------------------------------------------
# The package ships its own registration declaration
# ---------------------------------------------------------------------------

def test_context_declaration_matches_the_shipped_intrinsic_registry_entry():
    """The package owns its implementation module; INTRINSICS publishes it."""
    declaration = CONTEXT_PLUGIN.intrinsic_declaration()
    entry = registry.INTRINSICS[declaration["name"]]
    assert entry["module"].__name__ == declaration["module"]


def test_declaration_names_the_declaring_package_and_stamps_the_kernel_source():
    declaration = CONTEXT_PLUGIN.intrinsic_declaration()
    assert declaration["name"] == "context"
    assert declaration["module"] == "lingtai.tools.context"
    assert declaration["source"] == _plugin.INTRINSIC_SOURCE == "lingtai-intrinsic"
    assert declaration["summary"] and declaration["homepage"]


def test_the_registry_mapping_is_unchanged_and_still_the_runtime_source():
    """The descriptor documents the record; it does not replace registry I/O."""
    assert registry.INTRINSICS["context"] == {"module": context_tool}
    assert "context" not in registry.BUILTIN_TOOLS
    assert "context" not in registry.CORE_DEFAULTS


# ---------------------------------------------------------------------------
# The manual is an owned, packaged skill — and the host mounts it
# ---------------------------------------------------------------------------

def test_the_package_ships_the_bundle_and_no_standalone_copy_survives():
    bundle = _REPO_ROOT / "src/lingtai/tools/context/manual"
    assert (bundle / "SKILL.md").is_file()
    assert (bundle / "assets/molt-template.md").is_file()
    assert (bundle / "assets/session-journal-entry-template.md").is_file()
    assert (bundle / "reference/summarize-manual/SKILL.md").is_file()
    # The bundle lives with its owner now, so the tool-less standalone catalog
    # must not keep a second copy the installer could win or lose a race with.
    assert not (_REPO_ROOT / "src/lingtai/intrinsic_skills/context-manual").exists()
    assert Path(CONTEXT_PLUGIN.skill_path) == bundle / "SKILL.md"


def test_the_host_mount_agrees_with_the_mount_the_descriptor_declares():
    mount = CONTEXT_PLUGIN.manual_mount()
    assert mount["package"] == "lingtai.tools.context"
    assert mount["bundle"] == "manual/"
    assert mount["install_root"] == ".library/intrinsic/capabilities"
    # The host decides; the descriptor states what it expects. Neither side may
    # drift alone — the installed name is the long-established skill name.
    assert Agent._MANUAL_MOUNT_NAMES["context"] == mount["installed_dir"]
    assert mount["installed_dir"] == mount["skill"] == CONTEXT_PLUGIN.skill_name


def test_the_real_installer_mounts_the_packaged_bundle_with_its_sidecars(tmp_path):
    _install_manuals(tmp_path)

    mount = CONTEXT_PLUGIN.manual_mount()
    installed = tmp_path / mount["install_root"] / mount["installed_dir"]
    packaged = Path(CONTEXT_PLUGIN.skill_path).parent

    assert (installed / "SKILL.md").read_text(encoding="utf-8") == (
        packaged / "SKILL.md"
    ).read_text(encoding="utf-8")
    for sidecar in (
        "assets/molt-template.md",
        "assets/session-journal-entry-template.md",
        "reference/summarize-manual/SKILL.md",
    ):
        assert (installed / sidecar).read_text(encoding="utf-8") == (
            packaged / sidecar
        ).read_text(encoding="utf-8")
    # Packaging the manual into its tool did not rename the skill: the
    # destination the prompts, the skills catalog, and every cross-manual
    # reference already point at is exactly what was written.
    assert installed.name == "context-manual"


def test_manual_answers_from_the_installed_bundle_at_a_model_readable_path(tmp_path):
    _install_manuals(tmp_path)
    agent = _StubAgent(tmp_path)

    result = context_tool.handle(agent, {"action": "manual", "input": {}})

    mount = CONTEXT_PLUGIN.manual_mount()
    expected_path = (
        tmp_path / mount["install_root"] / mount["installed_dir"] / "SKILL.md"
    )
    assert result["status"] == "ok"
    assert result["manual_path"] == str(expected_path)
    assert result["manual"] == expected_path.read_text(encoding="utf-8")
    # The installed document is the packaged one, so the body behind the action
    # is this package's own skill and carries its frontmatter name.
    assert f"name: {CONTEXT_PLUGIN.skill_name}" in result["manual"]
    assert CONTEXT_PLUGIN.skill_body in result["manual"]
    # Flat public shape, unchanged: no ``content``/``structuredContent`` wrapper.
    assert set(result) == {"status", "manual", "manual_path"}


def test_the_package_local_skill_name_is_an_alias_not_a_second_spelling():
    """One declared value behind both the mount and the loader."""
    assert (
        context_tool._MANUAL_SKILL_NAME
        == CONTEXT_PLUGIN.skill_name
        == CONTEXT_PLUGIN.skill_frontmatter["name"]
        == "context-manual"
    )


def test_manual_degrades_truthfully_when_nothing_is_installed(tmp_path):
    result = context_tool.handle(_StubAgent(tmp_path), {"action": "manual", "input": {}})
    assert result["status"] == "degraded"
    assert result["manual"] == ""
    assert "context-manual" in result["error"]


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and owned by the plugin
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in CONTEXT_DECLARED_ACTIONS
    assert CONTEXT_ACTIONS == (*CONTEXT_DECLARED_ACTIONS, "manual")
    assert CONTEXT_ACTIONS[-1] == "manual"
    assert context_tool.ACTION_ORDER == CONTEXT_ACTIONS


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: CONTEXT_PLUGIN.actions(["molt", "manual"]), id="actions"),
        pytest.param(
            lambda: CONTEXT_PLUGIN.action_input_schemas({"molt": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: CONTEXT_PLUGIN.build_family(
                [
                    ChildTool("molt", {"type": "object"}, lambda _i: {}),
                    ChildTool("manual", {"type": "object"}, lambda _i: {"hijacked": True}),
                ],
                None,
            ),
            id="family",
        ),
    ],
)
def test_a_package_cannot_declare_re_schema_or_rebind_the_reserved_manual(compose):
    with pytest.raises(IntrinsicToolPluginError, match="reserved 'manual'"):
        compose()


def test_composed_family_always_carries_a_manual_child_with_a_strict_empty_input():
    family = CONTEXT_PLUGIN.build_family(context_tool._build_declared_children(None), None)
    assert family.has_manual()
    assert family.child_names == CONTEXT_ACTIONS
    assert _plugin.strict_empty_input_schema() == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def test_strict_empty_input_schema_hands_out_independent_copies():
    first = _plugin.strict_empty_input_schema()
    first["properties"]["smuggled"] = {"type": "string"}
    assert _plugin.strict_empty_input_schema()["properties"] == {}


# ---------------------------------------------------------------------------
# The public envelope shape is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_context_family_shape():
    schema = context_tool.get_schema()
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == list(CONTEXT_ACTIONS)
    assert "context-manual" in schema["properties"]["action"]["description"]


def test_declared_actions_still_dispatch_into_their_own_handlers(tmp_path, monkeypatch):
    seen: list[dict] = []
    monkeypatch.setattr(
        context_tool,
        "_summarize_engine",
        lambda agent, args: seen.append(dict(args)) or {"status": "ok"},
    )
    result = context_tool.handle(
        _StubAgent(tmp_path),
        {
            "action": "summarize",
            "input": {"items": [{"tool_call_id": "t1", "summary": "short"}]},
            "reasoning": "compact one result",
        },
    )
    assert result == {"status": "ok"}
    assert seen == [
        {"items": [{"tool_call_id": "t1", "summary": "short"}], "rebuild": False}
    ]


def test_unknown_action_error_is_still_context_shaped(tmp_path):
    result = context_tool.handle(_StubAgent(tmp_path), {"action": "nope", "input": {}})
    assert result["error"] == (
        "Unknown context action: nope. Must be one of: molt, summarize, rebuild, manual."
    )


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_package_that_is_not_its_own_module():
    with pytest.raises(IntrinsicToolPluginError, match="must be the 'context' module"):
        IntrinsicToolPlugin(**{**_DESCRIPTOR_FIELDS, "package": "lingtai.tools.system"})


def test_descriptor_rejects_a_manual_that_is_not_the_packaged_skill():
    with pytest.raises(IntrinsicToolPluginError, match="declares name"):
        IntrinsicToolPlugin(
            **{**_DESCRIPTOR_FIELDS, "skill_name": "somebody-elses-manual"}
        )


def test_descriptor_rejects_a_package_that_ships_no_bundle():
    with pytest.raises(IntrinsicToolPluginError, match="ships no manual/SKILL.md"):
        IntrinsicToolPlugin(
            name="pad",
            package="lingtai.tools.pad",
            summary="s",
            homepage="h",
            skill_name="pad-manual",
        )


@pytest.mark.parametrize("blank_field", sorted(_DESCRIPTOR_FIELDS))
def test_descriptor_rejects_blank_identity_fields(blank_field):
    with pytest.raises(IntrinsicToolPluginError, match="non-empty string"):
        IntrinsicToolPlugin(**{**_DESCRIPTOR_FIELDS, blank_field: "  "})


def test_descriptor_rejects_an_empty_or_duplicated_action_list():
    with pytest.raises(IntrinsicToolPluginError, match="at least one action"):
        CONTEXT_PLUGIN.actions([])
    with pytest.raises(IntrinsicToolPluginError, match="duplicate action"):
        CONTEXT_PLUGIN.actions(["molt", "molt"])

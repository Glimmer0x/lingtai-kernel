"""Tool-plugin packaging invariants, proven on the ``file`` reference slice.

A plugin-packaged built-in tool is a package that ships three things together:
the operation code, the bundled ``manual/SKILL.md`` the host installs into the
agent's intrinsic library, and the capability declaration the built-in registry
publishes for it. ``lingtai.tools._plugin.ToolPlugin`` binds those three and
owns the one promise a package must not be able to break — the reserved
``manual`` action, appended from the packaged skill rather than declared by the
package.

These tests pin the packaging promise, the runtime discovery/mount agreement
(registry tables and the manual install destination), and the *unchanged*
public file surface around it. They touch only tmp_path working trees.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from lingtai.tools import _plugin
from lingtai.tools import file as file_tool
from lingtai.tools._plugin import ToolPlugin, ToolPluginError
from lingtai.tools.file.plugin import (
    FILE_ACTIONS,
    FILE_DECLARED_ACTIONS,
    FILE_PLUGIN,
)
from lingtai.agent import Agent
from lingtai.tools.tool_family import ChildTool
from tests._service_helpers import make_gemini_mock_service as make_mock_service

_REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def file_agent(tmp_path):
    """One booted agent with the ``file`` capability and its installed library."""
    workdir = tmp_path / "test"
    agent = Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities=["file"],
    )
    yield agent, workdir
    agent.stop(timeout=1.0)


def _call(agent, action, input_, **root):
    return agent._tool_handlers["file"](
        {"action": action, "input": input_, "reasoning": "focused test", **root}
    )


# ---------------------------------------------------------------------------
# The package ships its own capability declaration
# ---------------------------------------------------------------------------

def test_declaration_matches_the_shipped_builtin_registry_entries():
    """The package owns its capability record; the registry publishes exactly it."""
    from lingtai.tools import registry

    declaration = FILE_PLUGIN.capability_declaration()
    assert declaration["name"] == "file"
    assert registry.BUILTIN_TOOLS["file"] == declaration["module"]
    assert registry.CORE_DEFAULTS["file"] == declaration["defaults"]


def test_declaration_names_the_declaring_package_and_its_own_providers():
    declaration = FILE_PLUGIN.capability_declaration()
    assert declaration["module"] == file_tool.__name__ == "lingtai.tools.file"
    assert declaration["providers"] == file_tool.PROVIDERS
    # ``get_all_providers`` reads the module attribute; the module aliases the
    # plugin, so the CLI and the descriptor cannot disagree.
    from lingtai.tools import registry

    assert registry.get_all_providers()["file"] == declaration["providers"]


def test_registry_lookup_is_unchanged_and_still_the_runtime_source():
    """The descriptor documents the record; it does not replace registry lookup."""
    from lingtai.tools import registry

    assert registry.BUILTIN_TOOLS["file"] == FILE_PLUGIN.package
    assert registry.canonical_capability_name("file") == FILE_PLUGIN.name


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the packaged skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in FILE_DECLARED_ACTIONS
    assert FILE_ACTIONS == (*FILE_DECLARED_ACTIONS, "manual")
    assert FILE_ACTIONS[-1] == "manual"
    assert file_tool.ACTIONS == FILE_ACTIONS


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: FILE_PLUGIN.actions(["read", "manual"]), id="actions"),
        pytest.param(
            lambda: FILE_PLUGIN.action_input_schemas({"read": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: FILE_PLUGIN.build_family(
                [
                    ChildTool("read", {"type": "object"}, lambda _i: {}),
                    ChildTool("manual", {"type": "object"}, lambda _i: {"hijacked": True}),
                ]
            ),
            id="family",
        ),
    ],
)
def test_a_package_cannot_declare_re_schema_or_rebind_the_reserved_manual(compose):
    with pytest.raises(ToolPluginError, match="reserved 'manual'"):
        compose()


def test_composed_family_always_carries_a_manual_child_with_a_strict_empty_input():
    family = file_tool._build_family()
    assert family.has_manual()
    assert family.child_names == FILE_ACTIONS
    assert file_tool.ACTION_INPUT_SCHEMAS["manual"] == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def test_the_packaged_skill_is_the_manual_this_plugin_owns():
    packaged = _REPO_ROOT / "src/lingtai/tools/file/manual/SKILL.md"
    assert packaged.is_file()
    assert Path(FILE_PLUGIN.skill_path).name == "SKILL.md"
    assert FILE_PLUGIN.skill_frontmatter["name"] == "file-manual"
    assert FILE_PLUGIN.skill_body.strip()
    assert packaged.read_text(encoding="utf-8").endswith(FILE_PLUGIN.skill_body)
    # The manual is no longer a standalone kernel skill bundle: the package owns it.
    assert not (_REPO_ROOT / "src/lingtai/intrinsic_skills/file-manual").exists()


# ---------------------------------------------------------------------------
# The host mounts the packaged manual where the plugin declares
# ---------------------------------------------------------------------------

def test_manual_destination_is_the_capability_name_the_installer_computes():
    assert FILE_PLUGIN.manual_destination == FILE_PLUGIN.name == "file"
    assert file_tool.FAMILY_MANUAL_SKILL == FILE_PLUGIN.manual_destination


def test_host_installs_the_packaged_bundle_and_manual_answers_from_it(file_agent):
    agent, workdir = file_agent
    installed = (
        workdir
        / ".library"
        / "intrinsic"
        / "capabilities"
        / FILE_PLUGIN.manual_destination
        / "SKILL.md"
    )
    assert installed.is_file()
    installed_body = installed.read_text(encoding="utf-8")
    packaged = Path(FILE_PLUGIN.skill_path).read_text(encoding="utf-8")
    assert installed_body == packaged

    result = _call(agent, "manual", {})
    assert result["status"] == "ok"
    assert result["content"][0]["text"] == installed_body
    assert result["structuredContent"]["manual_path"] == str(installed)
    # Host boundary preserved: the model-visible path is workdir-local, not the
    # kernel's installed package path.
    assert str(workdir) in result["structuredContent"]["manual_path"]


def test_manual_does_not_reach_any_file_operation(file_agent, monkeypatch):
    """The plugin-owned manual child never enters the manager's bound operations."""
    agent, _workdir = file_agent

    def explode(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("manual must not perform target file I/O")

    for method in ("read", "write", "glob", "grep"):
        monkeypatch.setattr(agent._file_io, method, explode)

    result = _call(agent, "manual", {})
    assert result["status"] == "ok"
    assert result["content"][0]["text"]


def test_manual_still_rejects_a_non_empty_input_like_every_other_action(file_agent):
    agent, _workdir = file_agent
    rejected = _call(agent, "manual", {"topic": "read"})
    assert rejected["status"] == "failed"
    assert rejected["error_code"] == "INVALID_ARGUMENT"


# ---------------------------------------------------------------------------
# The public envelope shape is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_action_family_shape():
    schema = file_tool.get_schema()
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == list(FILE_ACTIONS)
    assert len(schema["allOf"]) == len(FILE_ACTIONS)
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    assert branch_titles == [f"{action} input" for action in FILE_ACTIONS]


def test_declared_actions_still_reach_their_own_operations(file_agent):
    """Sandbox/read/write/edit behavior is unchanged by the plugin packaging."""
    agent, workdir = file_agent
    target = workdir / "probe.txt"
    written = _call(
        agent, "write", {"file_path": str(target), "content": "alpha\nbeta\n"}
    )
    assert written["status"] == "ok"
    read_back = _call(
        agent,
        "read",
        {"file_path": str(target), "offset": None, "limit": None, "max_chars": None},
    )
    assert "alpha" in read_back["content"]
    edited = _call(
        agent,
        "edit",
        {
            "file_path": str(target),
            "old_string": "beta",
            "new_string": "gamma",
            "replace_all": None,
        },
    )
    assert edited["status"] == "ok"
    assert target.read_text(encoding="utf-8") == "alpha\ngamma\n"


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_package_that_is_not_its_own_module():
    with pytest.raises(ToolPluginError, match="must be the 'file' module"):
        ToolPlugin(
            name="file",
            package="lingtai.tools.email",
            module_dir="file",
            summary="s",
            skill_name="file-manual",
        )


def test_descriptor_rejects_a_manual_that_is_not_the_packaged_skill():
    with pytest.raises(ToolPluginError, match="declares name"):
        ToolPlugin(
            name="file",
            package="lingtai.tools.file",
            module_dir="file",
            summary="s",
            skill_name="somebody-elses-manual",
        )


def test_descriptor_rejects_a_package_with_no_packaged_manual():
    with pytest.raises(ToolPluginError, match="ships no manual/SKILL.md"):
        ToolPlugin(
            name="context",
            package="lingtai.tools.context",
            module_dir="context",
            summary="s",
            skill_name="context-manual",
        )


@pytest.mark.parametrize("blank_field", ["name", "package", "module_dir", "summary", "skill_name"])
def test_descriptor_rejects_blank_identity_fields(blank_field):
    fields = {
        "name": "file",
        "package": "lingtai.tools.file",
        "module_dir": "file",
        "summary": "s",
        "skill_name": "file-manual",
    }
    fields[blank_field] = "  "
    with pytest.raises(ToolPluginError, match="non-empty string"):
        ToolPlugin(**fields)


@pytest.mark.parametrize("bad_field", ["defaults", "providers"])
def test_descriptor_rejects_non_mapping_declaration_fields(bad_field):
    fields = {
        "name": "file",
        "package": "lingtai.tools.file",
        "module_dir": "file",
        "summary": "s",
        "skill_name": "file-manual",
        bad_field: ["not", "a", "mapping"],
    }
    with pytest.raises(ToolPluginError, match="must be a mapping"):
        ToolPlugin(**fields)


def test_descriptor_declaration_is_a_copy_callers_cannot_mutate():
    first = FILE_PLUGIN.capability_declaration()
    first["defaults"]["yolo"] = True
    first["providers"]["default"] = "hijacked"
    assert FILE_PLUGIN.capability_declaration() == {
        "name": "file",
        "module": "lingtai.tools.file",
        "defaults": {},
        "providers": {"providers": [], "default": "builtin"},
        "manual_destination": "file",
    }

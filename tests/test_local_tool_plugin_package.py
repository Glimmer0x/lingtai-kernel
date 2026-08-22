"""Local-tool plugin packaging invariants, proven on the Task Card reference slice.

A built-in capability is a plugin-style package: the same folder ships the
handler, the bundled ``manual/SKILL.md``, and the mount record the built-in
registry publishes. ``lingtai.tools._plugin.LocalToolPlugin`` binds those three
and owns the one promise a package must not be able to break — the reserved
``manual`` action, appended from the packaged skill rather than declared by the
package.

These tests pin the packaging promise and the *unchanged* public Task Card
surface around it. They start no renderer subprocess and write no artifact: the
schema, the manual, and the descriptor are all independent of a live watch.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from lingtai.tools import _plugin
from lingtai.tools import task_card as task_card_tool
from lingtai.tools._plugin import LocalToolPlugin, LocalToolPluginError
from lingtai.tools.registry import BUILTIN_TOOLS, CORE_DEFAULTS
from lingtai.tools.task_card.plugin import (
    TASK_CARD_ACTIONS,
    TASK_CARD_DECLARED_ACTIONS,
    TASK_CARD_PLUGIN,
)
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA

_REPO_ROOT = Path(__file__).resolve().parents[1]

_VALID_FIELDS = {
    "name": "task_card",
    "package": "lingtai.tools.task_card",
    "summary": "s",
    "manual_skill": "task_card",
    "skill_name": "task_card-manual",
}


class _StubAgent:
    """Minimal duck-typed agent: a working dir plus ``add_tool`` capture."""

    def __init__(self, working_dir: Path) -> None:
        self._working_dir = working_dir
        self.mounted: dict[str, dict] = {}

    def add_tool(self, name: str, **kwargs) -> None:
        self.mounted[name] = kwargs


def _install_manual(workdir: Path, skill_name: str, body: str) -> Path:
    path = (
        workdir / ".library" / "intrinsic" / "capabilities" / skill_name / "SKILL.md"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The package ships its own mount record
# ---------------------------------------------------------------------------

def test_task_card_declaration_matches_the_shipped_builtin_registry_entries():
    """The package owns its mount; the registry publishes exactly it."""
    declaration = TASK_CARD_PLUGIN.tool_declaration()
    assert BUILTIN_TOOLS[declaration["name"]] == declaration["module"]
    assert CORE_DEFAULTS[declaration["name"]] == declaration["default_configuration"]


def test_declaration_mounts_the_declaring_package_and_carries_the_intrinsic_source():
    declaration = TASK_CARD_PLUGIN.tool_declaration()
    assert declaration["name"] == "task_card"
    assert declaration["module"] == "lingtai.tools.task_card"
    assert declaration["source"] == _plugin.INTRINSIC_SOURCE
    assert declaration["manual_skill"] == "task_card"
    assert declaration["summary"].strip()


def test_registry_loading_is_unchanged_and_still_the_runtime_source():
    """The descriptor documents the record; it does not replace registry I/O.

    Importing the registry must stay cheap (``registry.py``'s import
    discipline), so it keeps its own literals rather than importing this — or
    any — tool package to generate them. This is the same split the curated-MCP
    reference uses with ``mcp_catalog.json``: the shipped file stays the runtime
    source and the descriptor is what it must agree with.
    """
    probe = (
        "import sys; import lingtai.tools.registry as r; "
        "print(r.BUILTIN_TOOLS['task_card']); "
        "print('lingtai.tools.task_card' in sys.modules)"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(_REPO_ROOT),
    )
    assert completed.returncode == 0, completed.stderr
    module, eagerly_imported = completed.stdout.split()
    assert module == "lingtai.tools.task_card"
    assert eagerly_imported == "False"


def test_setup_mounts_the_tool_under_the_descriptor_name(tmp_path: Path):
    agent = _StubAgent(tmp_path)
    task_card_tool.setup(agent)
    assert list(agent.mounted) == [TASK_CARD_PLUGIN.name] == ["task_card"]
    assert agent.mounted["task_card"]["schema"] == task_card_tool.get_schema()
    assert agent.mounted["task_card"]["description"] == task_card_tool.get_description()


# ---------------------------------------------------------------------------
# The packaged skill is the plugin's own, at both ends of the install
# ---------------------------------------------------------------------------

def test_packaged_skill_is_the_bundle_the_agent_library_installs_from():
    bundle = Path(TASK_CARD_PLUGIN.manual_bundle_path())
    assert bundle == _REPO_ROOT / "src/lingtai/tools/task_card/manual"
    assert Path(TASK_CARD_PLUGIN.skill_path) == bundle / "SKILL.md"
    assert TASK_CARD_PLUGIN.skill_frontmatter["name"] == "task_card-manual"
    assert TASK_CARD_PLUGIN.skill_body.strip()


def test_installed_manual_path_is_the_destination_the_agent_installer_writes(tmp_path: Path):
    assert TASK_CARD_PLUGIN.installed_manual_path(tmp_path) == (
        tmp_path
        / ".library"
        / "intrinsic"
        / "capabilities"
        / TASK_CARD_PLUGIN.manual_skill
        / "SKILL.md"
    )


def test_agent_installer_destination_agrees_with_the_declared_manual_skill():
    """``Agent._install_intrinsic_manuals`` derives the same directory name.

    The installer scans package folders rather than importing them, so this
    pins the convention the descriptor declares: no alias rewrite applies to
    ``task_card``, and the folder it copies is this plugin's bundle.
    """
    package_dir = _REPO_ROOT / "src/lingtai/tools/task_card"
    assert package_dir.name == TASK_CARD_PLUGIN.manual_skill
    assert (package_dir / _plugin.MANUAL_BUNDLE_DIRNAME / "SKILL.md").is_file()


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the packaged skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in TASK_CARD_DECLARED_ACTIONS
    assert TASK_CARD_ACTIONS == (*TASK_CARD_DECLARED_ACTIONS, "manual")
    assert TASK_CARD_ACTIONS[-1] == "manual"


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: TASK_CARD_PLUGIN.actions(["start", "manual"]), id="actions"),
        pytest.param(
            lambda: TASK_CARD_PLUGIN.action_input_schemas({"start": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: TASK_CARD_PLUGIN.build_family(
                [
                    ChildTool("start", {"type": "object"}, lambda _i: {}),
                    ChildTool("manual", {"type": "object"}, lambda _i: {"hijacked": True}),
                ]
            ),
            id="family",
        ),
    ],
)
def test_a_package_cannot_declare_re_schema_or_rebind_the_reserved_manual(compose):
    with pytest.raises(LocalToolPluginError, match="reserved 'manual'"):
        compose()


def test_composed_family_always_carries_a_manual_child_with_a_strict_empty_input(tmp_path: Path):
    agent = _StubAgent(tmp_path)
    family = task_card_tool.TaskCardManager(agent)._family()
    assert family.has_manual()
    assert family.child_names == TASK_CARD_ACTIONS
    assert task_card_tool._INPUT_SCHEMAS["manual"] == MANUAL_INPUT_SCHEMA


def test_manual_answers_from_the_installed_bundle_without_entering_the_manager(tmp_path: Path):
    agent = _StubAgent(tmp_path)
    body = "---\nname: task_card-manual\n---\n\n# installed sentinel\n"
    installed = _install_manual(tmp_path, TASK_CARD_PLUGIN.manual_skill, body)

    manager = task_card_tool.TaskCardManager(agent)
    result = manager.handle({"action": "manual", "input": {}, "reasoning": "read it"})

    assert result["status"] == "ok"
    assert result["content"][0]["text"] == body
    assert result["structuredContent"]["manual_path"] == str(installed)
    # No watch was started and no artifact written by reading the manual.
    assert not (tmp_path / "taskcard").exists()


def test_manual_falls_back_to_the_packaged_skill_when_nothing_is_installed(tmp_path: Path):
    """A plugin owns its skill, so its manual is always answerable."""
    manager = task_card_tool.TaskCardManager(_StubAgent(tmp_path))
    result = manager.handle({"action": "manual", "input": {}, "reasoning": "read it"})

    assert result == TASK_CARD_PLUGIN.packaged_manual_result()
    assert result["status"] == "ok"
    assert result["content"][0]["text"] == TASK_CARD_PLUGIN.skill_body
    assert result["structuredContent"]["manual_path"] == TASK_CARD_PLUGIN.skill_path
    assert "error" not in result
    assert not (tmp_path / ".library").exists()


def test_manual_still_rejects_a_non_empty_input_like_every_other_action(tmp_path: Path):
    manager = task_card_tool.TaskCardManager(_StubAgent(tmp_path))
    rejected = manager.handle(
        {"action": "manual", "input": {"topic": "start"}, "reasoning": "x"}
    )
    assert rejected["status"] == "failed"


# ---------------------------------------------------------------------------
# The public envelope shape is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_action_family_shape():
    schema = task_card_tool.get_schema()
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == list(TASK_CARD_ACTIONS)
    assert len(schema["allOf"]) == len(TASK_CARD_ACTIONS)
    assert "task_card-manual" in schema["properties"]["action"]["description"]
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    assert branch_titles == [f"{action} input" for action in TASK_CARD_ACTIONS]


def test_advertised_action_inventory_cannot_drift_from_the_composed_family():
    description = task_card_tool.get_description()
    assert description.endswith("Actions: " + ", ".join(TASK_CARD_ACTIONS) + ".")


def test_declared_actions_still_dispatch_into_the_manager(tmp_path: Path):
    manager = task_card_tool.TaskCardManager(_StubAgent(tmp_path))
    result = manager.handle(
        {"action": "inspect", "input": {"watch_id": "nope"}, "reasoning": "probe"}
    )
    # The manager's own domain refusal — not a family/packaging rejection.
    assert result == {"status": "failed", "message": "unknown watch_id: nope"}


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_package_that_is_not_its_own_module():
    with pytest.raises(LocalToolPluginError, match="must be the 'task_card' module"):
        LocalToolPlugin(**{**_VALID_FIELDS, "package": "lingtai.tools.avatar"})


def test_descriptor_accepts_a_retained_implementation_folder_via_module_name():
    """``bash`` → ``shell`` stays expressible without weakening the check."""
    shell = LocalToolPlugin(
        name="shell",
        package="lingtai.tools.bash",
        summary="s",
        manual_skill="shell",
        skill_name="shell-manual",
        module_name="bash",
    )
    assert shell.tool_declaration()["module"] == "lingtai.tools.bash"
    assert shell.tool_declaration()["name"] == "shell"
    # The folder is still checked — against ``module_name``, not the public name.
    with pytest.raises(LocalToolPluginError, match="must be the 'bash' module"):
        LocalToolPlugin(**{**_VALID_FIELDS, "name": "shell", "module_name": "bash"})


def test_descriptor_rejects_a_manual_that_is_not_the_packaged_skill():
    with pytest.raises(LocalToolPluginError, match="declares name"):
        LocalToolPlugin(**{**_VALID_FIELDS, "skill_name": "somebody-elses-manual"})


def test_descriptor_rejects_a_package_with_no_packaged_manual_bundle():
    with pytest.raises(LocalToolPluginError, match="has no packaged"):
        LocalToolPlugin(
            **{
                **_VALID_FIELDS,
                "name": "psyche",
                "package": "lingtai.tools.psyche",
                "manual_skill": "psyche",
            }
        )


@pytest.mark.parametrize("blank_field", sorted(_VALID_FIELDS))
def test_descriptor_rejects_blank_identity_fields(blank_field):
    with pytest.raises(LocalToolPluginError, match="non-empty string"):
        LocalToolPlugin(**{**_VALID_FIELDS, blank_field: "  "})


def test_descriptor_rejects_a_non_mapping_default_configuration():
    with pytest.raises(LocalToolPluginError, match="must be a mapping or None"):
        LocalToolPlugin(**{**_VALID_FIELDS, "default_configuration": ["nope"]})

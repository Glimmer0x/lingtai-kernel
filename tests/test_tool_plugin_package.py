"""Tool-plugin packaging invariants, proven on the ``plugin`` capability slice.

A built-in tool is a plugin-style package: the same folder ships the handler
code, the bundled ``manual/SKILL.md``, and the capability declaration the
built-in registry publishes for it. ``lingtai.tools._plugin.ToolPlugin`` binds
those three and owns the one promise a package must not be able to break — the
reserved ``manual`` action, appended from the packaged skill rather than declared
by the package.

The ``plugin`` capability is the deliberate first slice, because it is the one
place the packaging could eat itself. It is the model-facing tool that *reports*
Agent Plugins (agent-plugins.org v1.0.0), so "the plugin tool is a plugin" is
either a precise statement about two different things or a recursion. These tests
pin which: a **tool plugin** is a kernel-shipped Python package under
``lingtai.tools``, an **Agent Plugin** is a third-party directory carrying
``plugin.json``, and the ``plugin`` package is the first and never the second —
it ships no manifest, is invisible to ``read_plugins``, is absent from its own
``info`` snapshot, and owns no ``source="plugin:plugin"`` record.

The unchanged public ``plugin`` surface around the packaging is pinned in
``tests/test_plugin_tool.py``; what is pinned here is that the surface is now
*composed from the descriptor* rather than from repeated literals.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from lingtai.tools import _plugin
from lingtai.tools._plugin import (
    ToolPlugin,
    ToolPluginError,
    declared_manual_destinations,
    iter_tool_plugins,
)
from lingtai.tools.plugin.plugin import (
    PLUGIN_ACTIONS,
    PLUGIN_DECLARED_ACTIONS,
    TOOL_PLUGIN,
)
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA
from tests._service_helpers import make_gemini_mock_service as make_mock_service

_REPO_ROOT = Path(__file__).resolve().parents[1]
_TOOLS_DIR = _REPO_ROOT / "src" / "lingtai" / "tools"


def _mk_agent(tmp_path: Path):
    from lingtai.agent import Agent

    workdir = tmp_path / "agent"
    return Agent(
        service=make_mock_service(),
        agent_name="test",
        working_dir=workdir,
        capabilities={"plugin": {}},
    ), workdir


@pytest.fixture
def foreign_package(tmp_path, monkeypatch):
    """An importable stand-in tool package, outside the real source tree.

    ``ToolPlugin`` requires its package to live under ``lingtai.tools`` so a
    descriptor cannot advertise a module the built-in registry must not import.
    Exercising the *other* construction guards therefore needs that anchor
    repointed rather than the real tools package polluted, which is what this
    fixture does. It yields a builder returning the package's dotted name.
    """
    root = tmp_path / "site"
    (root / "faketools").mkdir(parents=True)
    build_root = root / "faketools"
    (root / "faketools" / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.setattr(_plugin, "_TOOLS_PACKAGE", "faketools")

    created: list[str] = []

    def build(name: str, *, skill: str | None, manifest: bool = False) -> str:
        package_dir = root / "faketools" / name
        package_dir.mkdir(parents=True)
        (package_dir / "__init__.py").write_text("", encoding="utf-8")
        if skill is not None:
            (package_dir / "manual").mkdir()
            (package_dir / "manual" / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: a stand-in manual\n---\nbody\n",
                encoding="utf-8",
            )
        if manifest:
            (package_dir / "plugin.json").write_text("{}", encoding="utf-8")
        created.append(f"faketools.{name}")
        return f"faketools.{name}"

    build.root = build_root  # type: ignore[attr-defined]
    yield build

    for module in ("faketools", *created):
        sys.modules.pop(module, None)


# ---------------------------------------------------------------------------
# The package ships its own capability declaration
# ---------------------------------------------------------------------------

def test_package_declaration_matches_the_built_in_registry_entry():
    """The package owns its module path; the registry publishes exactly it."""
    from lingtai.tools.registry import BUILTIN_TOOLS, CORE_DEFAULTS

    declaration = TOOL_PLUGIN.capability_declaration()
    assert BUILTIN_TOOLS[declaration["name"]] == declaration["module"]
    assert declaration["module"] == "lingtai.tools.plugin"
    assert declaration["default_on"] is True
    assert CORE_DEFAULTS[declaration["name"]] == declaration["default_kwargs"] == {}


def test_the_registry_tables_stay_the_runtime_source():
    """The descriptor documents the entry; it does not replace registry lookup.

    ``setup_capability`` must keep resolving the module through ``BUILTIN_TOOLS``
    with ``importlib`` *inside* the call, so importing the registry never imports
    every tool. Pinning that here is what stops a later "just read the
    descriptor" refactor from making the registry eagerly import the world.
    """
    from lingtai.tools import registry

    source = Path(registry.__file__).read_text(encoding="utf-8")
    assert "lingtai.tools._plugin" not in source
    assert "importlib.import_module(module_path)" in source


def test_declaration_is_a_plain_snapshot_and_never_a_plugin_source_stamp():
    declaration = TOOL_PLUGIN.capability_declaration()
    assert "plugin:" not in repr(declaration)
    assert set(declaration) == {
        "name", "module", "summary", "manual_destination", "default_on", "default_kwargs",
    }


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the packaged skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in PLUGIN_DECLARED_ACTIONS
    assert PLUGIN_DECLARED_ACTIONS == ("info",)
    assert PLUGIN_ACTIONS == (*PLUGIN_DECLARED_ACTIONS, "manual")
    assert PLUGIN_ACTIONS[-1] == "manual"


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: TOOL_PLUGIN.actions(["info", "manual"]), id="actions"),
        pytest.param(
            lambda: TOOL_PLUGIN.action_input_schemas({"info": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: TOOL_PLUGIN.build_family(
                [
                    ChildTool("info", {"type": "object"}, lambda _i: {}),
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


@pytest.mark.parametrize(
    "compose, match",
    [
        pytest.param(lambda: TOOL_PLUGIN.actions([]), "at least one action", id="empty"),
        pytest.param(
            lambda: TOOL_PLUGIN.actions(["info", "info"]), "duplicate action", id="duplicate"
        ),
    ],
)
def test_a_package_cannot_declare_an_empty_or_duplicated_action_list(compose, match):
    with pytest.raises(ToolPluginError, match=match):
        compose()


def test_composed_family_always_carries_a_manual_child_with_a_strict_empty_input():
    from lingtai.tools.plugin import _FAMILY

    assert _FAMILY.has_manual()
    assert _FAMILY.child_names == PLUGIN_ACTIONS
    assert TOOL_PLUGIN.action_input_schemas({"info": {}})["manual"] == MANUAL_INPUT_SCHEMA
    # The one owned literal, deep-copied — never a second spelling of it.
    assert _plugin.strict_empty_input_schema() is not MANUAL_INPUT_SCHEMA


def test_schema_advertises_the_packaged_skill_name_not_a_hand_copied_one():
    from lingtai.tools.plugin import get_schema

    action_desc = get_schema()["properties"]["action"]["description"]
    assert f"skill '{TOOL_PLUGIN.skill_name}'" in action_desc
    assert TOOL_PLUGIN.skill_name == "plugin-manual"
    # The declared half survives verbatim beside the appended manual line.
    assert "info: read-only action" in action_desc


def test_the_manual_catalog_line_is_bounded_prompt_weight():
    """A capability manual's frontmatter is a long router; the schema is not."""
    full = TOOL_PLUGIN.skill_frontmatter["description"]
    line = TOOL_PLUGIN.manual_action_description()
    assert len(full) > _plugin._MAX_MANUAL_DESCRIPTION_LEN
    assert line.endswith("…")
    assert len(line) < len(full)


def test_descriptor_owns_which_skill_the_manual_serves(tmp_path):
    """``manual`` answers from the installed copy of *this package's* bundle."""
    agent, workdir = _mk_agent(tmp_path)
    result = agent._tool_handlers["plugin"]({
        "action": "manual", "input": {}, "reasoning": "load plugin guidance",
    })
    installed = (
        workdir / ".library" / "intrinsic" / "capabilities"
        / TOOL_PLUGIN.manual_destination / "SKILL.md"
    )
    assert result["status"] == "ok"
    assert result["manual_path"] == str(installed)
    # Same document, both ends of the mount: what the package ships is what the
    # agent reads. (The install is verbatim, so the texts are identical.)
    assert result["plugin_manual"] == TOOL_PLUGIN.skill_text
    assert installed.read_text(encoding="utf-8") == TOOL_PLUGIN.skill_text


def test_a_renamed_or_missing_packaged_skill_fails_at_construction(foreign_package):
    with pytest.raises(ToolPluginError, match="expected 'expected-name'"):
        ToolPlugin(
            name="renamed",
            package=foreign_package("renamed", skill="something-else"),
            summary="s",
            skill_name="expected-name",
            manual_destination="renamed",
        )
    with pytest.raises(ToolPluginError, match="cannot read its packaged"):
        ToolPlugin(
            name="bare",
            package=foreign_package("bare", skill=None),
            summary="s",
            skill_name="bare-manual",
            manual_destination="bare",
        )


def test_a_descriptor_cannot_point_outside_the_built_in_tools_package():
    with pytest.raises(ToolPluginError, match="must live under 'lingtai.tools'"):
        ToolPlugin(
            name="elsewhere",
            package="somewhere.else",
            summary="s",
            skill_name="elsewhere-manual",
            manual_destination="elsewhere",
        )


# ---------------------------------------------------------------------------
# Runtime discovery and the manual mount contract
# ---------------------------------------------------------------------------

def test_discovery_finds_the_declared_tool_plugin():
    assert TOOL_PLUGIN in iter_tool_plugins()
    assert declared_manual_destinations()["plugin"] == "plugin"
    assert TOOL_PLUGIN.manual_mount() == ("plugin", "plugin")


def test_discovery_only_imports_packages_that_declare_a_descriptor():
    """Being discovered means being imported, so the scan must stay narrow.

    Every package the scan reaches is one whose ``__init__`` runs at boot, so a
    package without a ``plugin.py`` must not be touched. That is also what keeps
    the ``lingtai.tools`` → ``lingtai`` lazy-back-edge rule intact.
    """
    declaring = {
        entry.name
        for entry in _TOOLS_DIR.iterdir()
        if entry.is_dir()
        and not entry.name.startswith("_")
        and (entry / "plugin.py").is_file()
    }
    assert declaring == {p.manual_mount()[0] for p in iter_tool_plugins()}
    assert declaring == {"plugin"}


def test_the_host_installs_the_manual_where_the_package_declares(tmp_path):
    _agent, workdir = _mk_agent(tmp_path)
    capabilities = workdir / ".library" / "intrinsic" / "capabilities"
    assert (capabilities / TOOL_PLUGIN.manual_destination / "SKILL.md").is_file()
    # The retained non-descriptor mappings are untouched by the new contract.
    assert (capabilities / "shell" / "SKILL.md").is_file()
    assert (capabilities / "web" / "SKILL.md").is_file()
    assert not (capabilities / "bash").exists()
    assert not (capabilities / "web_search").exists()


def test_a_broken_descriptor_loses_its_declaration_without_taking_boot_down(
    foreign_package,
):
    broken = foreign_package.root / "broken"
    broken.mkdir()
    (broken / "__init__.py").write_text("", encoding="utf-8")
    (broken / "plugin.py").write_text("raise RuntimeError('boom')", encoding="utf-8")
    # The scan reports nothing for the broken package and does not propagate.
    assert declared_manual_destinations() == {}


# ---------------------------------------------------------------------------
# Non-recursion: a tool plugin is not an Agent Plugin
# ---------------------------------------------------------------------------

def test_the_plugin_tool_package_ships_no_agent_plugins_manifest():
    from lingtai.services.plugin_registry import MANIFEST_FILENAME

    assert not (_TOOLS_DIR / "plugin" / MANIFEST_FILENAME).exists()
    assert not any(
        (entry / MANIFEST_FILENAME).exists()
        for entry in _TOOLS_DIR.iterdir()
        if entry.is_dir()
    )


def test_a_tool_package_carrying_an_agent_plugins_manifest_is_rejected(foreign_package):
    """The guard is enforced, not merely documented."""
    with pytest.raises(ToolPluginError, match="is not an Agent Plugins v1.0.0 directory"):
        ToolPlugin(
            name="pretender",
            package=foreign_package("pretender", skill="pretender-manual", manifest=True),
            summary="s",
            skill_name="pretender-manual",
            manual_destination="pretender",
        )


def test_the_built_in_tools_tree_is_invisible_to_agent_plugin_discovery(tmp_path):
    """Pointing the Agent Plugins scanner at the kernel's own tools finds nothing."""
    from lingtai.services.plugin_registry import read_plugins

    records, problems, report = read_plugins(tmp_path, [str(_TOOLS_DIR)])
    assert records == []
    assert problems == []
    assert report[str(_TOOLS_DIR)]["exists"] is True
    assert report[str(_TOOLS_DIR)]["plugins"] == 0


def test_the_plugin_tool_never_reports_itself(tmp_path):
    agent, workdir = _mk_agent(tmp_path)
    snapshot = agent._tool_handlers["plugin"]({
        "action": "info", "input": {}, "reasoning": "inspect plugin state",
    })
    assert snapshot["status"] == "ok"
    names = [entry["name"] for entry in snapshot["registered"] + snapshot["discovered"]]
    assert TOOL_PLUGIN.name not in names
    assert snapshot["registered_count"] == snapshot["discovered_count"] == 0
    # ...and packaging it minted no registry record it would have to own.
    registry_file = workdir / "mcp_registry.jsonl"
    if registry_file.is_file():
        assert "plugin:plugin" not in registry_file.read_text(encoding="utf-8")

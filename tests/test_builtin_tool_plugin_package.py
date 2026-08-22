"""Built-in tool plugin packaging invariants, proven on the `mcp` slice.

`src/lingtai/tools/mcp/` is a real **Agent Plugins v1.0.0** package: a
`plugin.json` manifest, its manual as an owned Agent Skill under `skills/`, and
no `mcp.json` at all. These tests refuse to accept a descriptor-shaped
imitation, so each one is written against the thing the runtime actually reads:

- the manifest is validated by `services.plugin_registry.read_plugin` — the
  *same* reader a third-party plugin on a configured path goes through, not a
  private copy of the specification living in `lingtai.tools`;
- the manual is discovered as an owned skill by that reader, and the pre-plugin
  `manual/` directory convention is gone from the package;
- `Agent` mounts it from the manifest at boot, and the byte the model reads at
  `.library/intrinsic/capabilities/mcp/SKILL.md` is the plugin's own skill;
- pluginizing a *tool* stays outside the MCP registry: no `mcp.json` ships, no
  `source="plugin:mcp"` record is written, and a tool plugin that did carry
  servers would be reported and still not registered.

The public `mcp` surface is unchanged by all of this and is pinned here too, so
the packaging change cannot quietly move a model-facing value.
"""
from __future__ import annotations

import importlib
import itertools
import json
from pathlib import Path

import pytest

from lingtai.agent import Agent
from lingtai.services import plugin_registry
from lingtai.tools import _plugin
from lingtai.tools._plugin import (
    BuiltinToolPlugin,
    BuiltinToolPluginError,
    discover_tool_plugin,
)
from lingtai.tools.mcp import get_schema
from lingtai.tools.mcp.plugin import (
    MCP_ACTIONS,
    MCP_DECLARED_ACTIONS,
    MCP_TOOL_PLUGIN,
)
from lingtai.tools.tool_family import ChildTool
from tests._service_helpers import make_gemini_mock_service as make_mock_service

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PROBE_PACKAGE_NAMES = itertools.count()
_MCP_PACKAGE = _REPO_ROOT / "src/lingtai/tools/mcp"


@pytest.fixture
def mcp_agent(tmp_path):
    agent = Agent(
        service=make_mock_service(),
        agent_name="mcp-plugin-package",
        working_dir=tmp_path / "agent",
        capabilities={"mcp": {}},
    )
    try:
        yield agent, tmp_path / "agent"
    finally:
        agent.stop(timeout=1.0)


# ---------------------------------------------------------------------------
# The package is a real Agent Plugins v1.0.0 plugin
# ---------------------------------------------------------------------------

def test_package_ships_a_manifest_the_host_plugin_reader_accepts():
    """Not a descriptor: the file on disk passes the runtime's own reader."""
    record, problems = plugin_registry.read_plugin(_MCP_PACKAGE)

    assert problems == []
    assert record is not None
    assert record["name"] == "mcp"
    assert record["version"] == "1.0.0"
    assert record["source"] == str(_MCP_PACKAGE)


def test_manifest_declares_the_schema_version_this_kernel_understands():
    manifest = json.loads(
        (_MCP_PACKAGE / "plugin.json").read_text(encoding="utf-8")
    )
    assert manifest["$schema"] == plugin_registry.PLUGIN_SCHEMA_URL
    ok, error = plugin_registry.validate_manifest(manifest)
    assert (ok, error) == (True, None)


def test_the_tools_layer_does_not_fork_the_specification():
    """One owner for the filenames; `_plugin` re-states, never redefines."""
    assert _plugin.MANIFEST_FILENAME == plugin_registry.MANIFEST_FILENAME
    assert _plugin.MCP_CONFIG_FILENAME == plugin_registry.MCP_CONFIG_FILENAME
    assert _plugin.SKILLS_DIRNAME == plugin_registry.SKILLS_DIRNAME
    assert _plugin.SKILL_FILENAME == plugin_registry.SKILL_FILENAME


def test_extension_namespace_is_reverse_domain_and_client_specific():
    manifest = MCP_TOOL_PLUGIN.manifest
    assert _plugin.TOOL_EXTENSION_NAMESPACE == "ai.lingtai.tool"
    extension = manifest["extensions"][_plugin.TOOL_EXTENSION_NAMESPACE]
    assert extension == {
        "package": "lingtai.tools.mcp",
        "manual_skill": "mcp-manual",
    }
    # The specification's reader ignores namespaces it does not own, so the
    # kernel's own keys cannot change how any plugin is validated.
    ok, error = plugin_registry.validate_manifest(manifest)
    assert (ok, error) == (True, None)


# ---------------------------------------------------------------------------
# The manual is an owned skill, not a directory convention
# ---------------------------------------------------------------------------

def test_manual_is_an_owned_skill_discovered_by_the_plugin_reader():
    record, _problems = plugin_registry.read_plugin(_MCP_PACKAGE)

    assert record["skills"] == ["mcp-manual"]
    assert record["skill_count"] == 1
    assert record["skill_paths"] == [str(_MCP_PACKAGE / "skills" / "mcp-manual")]


def test_the_pre_plugin_manual_directory_convention_is_gone():
    assert not (_MCP_PACKAGE / "manual").exists()
    assert (_MCP_PACKAGE / "skills" / "mcp-manual" / "SKILL.md").is_file()


def test_owned_skill_keeps_its_reference_and_script_sidecars():
    skill_dir = MCP_TOOL_PLUGIN.skill_dir
    assert (skill_dir / "reference/curated-addons.md").is_file()
    assert (skill_dir / "reference/third-party-and-legacy.md").is_file()
    assert (skill_dir / "reference/troubleshooting.md").is_file()
    assert (skill_dir / "scripts/find_readme.py").is_file()


def test_descriptor_exposes_the_owned_skill_it_declares():
    assert MCP_TOOL_PLUGIN.skill_path == _MCP_PACKAGE / "skills/mcp-manual/SKILL.md"
    assert MCP_TOOL_PLUGIN.skill_frontmatter["name"] == "mcp-manual"
    assert MCP_TOOL_PLUGIN.skill_frontmatter["description"]
    assert MCP_TOOL_PLUGIN.skill_body.strip()
    assert not MCP_TOOL_PLUGIN.skill_body.lstrip().startswith("---")


# ---------------------------------------------------------------------------
# The descriptor cannot drift from the manifest
# ---------------------------------------------------------------------------

@pytest.fixture
def tool_package(tmp_path, monkeypatch):
    """Write a minimal importable tool package and return its module name.

    The descriptor resolves its own root through ``importlib.resources``, so a
    disagreement test has to be an actual importable package rather than a bare
    directory — that is exactly the resolution path a shipped tool uses. Package
    names come from a module-level counter: a name reused across tests would be
    served from ``sys.modules`` and silently resolve to the previous test's
    directory.
    """
    def make(
        *,
        declared_package: str | None = None,
        manual_skill: str = "probe-manual",
        skill: str | None = "probe-manual",
    ) -> str:
        package = f"_probe_tool_pkg_{next(_PROBE_PACKAGE_NAMES)}"
        root = tmp_path / package
        root.mkdir()
        (root / "__init__.py").write_text("", encoding="utf-8")
        (root / "plugin.json").write_text(
            json.dumps({
                "$schema": plugin_registry.PLUGIN_SCHEMA_URL,
                "name": "probe",
                "extensions": {
                    "ai.lingtai.tool": {
                        "package": declared_package or package,
                        "manual_skill": manual_skill,
                    },
                },
            }),
            encoding="utf-8",
        )
        if skill is not None:
            skill_dir = root / "skills" / skill
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                f"---\nname: {skill}\ndescription: probe\n---\nbody\n", encoding="utf-8"
            )
        monkeypatch.syspath_prepend(str(tmp_path))
        importlib.invalidate_caches()
        return package

    return make


def test_a_descriptor_whose_name_disagrees_with_the_manifest_raises(tool_package):
    package = tool_package()
    with pytest.raises(BuiltinToolPluginError, match="declares name 'probe'"):
        BuiltinToolPlugin(name="other", package=package, manual_skill="probe-manual")


def test_a_descriptor_whose_package_disagrees_with_the_manifest_raises(tool_package):
    package = tool_package(declared_package="lingtai.tools.mcp")
    with pytest.raises(BuiltinToolPluginError, match="declares package"):
        BuiltinToolPlugin(name="probe", package=package, manual_skill="probe-manual")


def test_a_descriptor_whose_manual_skill_disagrees_with_the_manifest_raises(
    tool_package,
):
    package = tool_package()
    with pytest.raises(BuiltinToolPluginError, match="declares manual_skill"):
        BuiltinToolPlugin(name="probe", package=package, manual_skill="elsewhere")


def test_a_manifest_naming_a_manual_skill_the_package_lacks_raises(tool_package):
    package = tool_package(skill=None)
    with pytest.raises(BuiltinToolPluginError, match="cannot read its owned manual skill"):
        BuiltinToolPlugin(name="probe", package=package, manual_skill="probe-manual")


def test_the_shipped_mcp_descriptor_agrees_with_its_own_manifest():
    assert MCP_TOOL_PLUGIN == BuiltinToolPlugin(
        name="mcp", package="lingtai.tools.mcp", manual_skill="mcp-manual"
    )


def test_a_package_without_a_manifest_cannot_be_a_tool_plugin():
    with pytest.raises(BuiltinToolPluginError, match="cannot read its plugin.json"):
        BuiltinToolPlugin(
            name="context", package="lingtai.tools.context", manual_skill="context-manual"
        )


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the owned skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in MCP_DECLARED_ACTIONS
    assert MCP_DECLARED_ACTIONS == ("info",)
    assert MCP_ACTIONS == (*MCP_DECLARED_ACTIONS, "manual")
    assert MCP_ACTIONS[-1] == "manual"


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: MCP_TOOL_PLUGIN.actions(["info", "manual"]), id="actions"),
        pytest.param(
            lambda: MCP_TOOL_PLUGIN.action_input_schemas({"info": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: MCP_TOOL_PLUGIN.build_family(
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
    with pytest.raises(BuiltinToolPluginError, match="reserved 'manual'"):
        compose()


def test_composed_family_always_carries_a_manual_child_with_a_strict_empty_input():
    family = MCP_TOOL_PLUGIN.build_family(
        [ChildTool("info", _plugin.strict_empty_input_schema(), lambda _i: {})]
    )
    assert family.has_manual()
    assert family.child_names == MCP_ACTIONS
    assert MCP_TOOL_PLUGIN.action_input_schemas({"info": {}})["manual"] == {
        "type": "object",
        "properties": {},
        "required": [],
        "additionalProperties": False,
    }


def test_the_manual_child_reads_the_mount_the_manifest_name_defines():
    assert MCP_TOOL_PLUGIN.mount_name == MCP_TOOL_PLUGIN.name == "mcp"


# ---------------------------------------------------------------------------
# Discovery / mount contract
# ---------------------------------------------------------------------------

def test_discovery_returns_the_mount_plan_the_manifest_declares():
    plan, problems = discover_tool_plugin(_MCP_PACKAGE)

    assert problems == []
    assert plan["name"] == "mcp"
    assert plan["version"] == "1.0.0"
    assert plan["manual_skill"] == "mcp-manual"
    # The owned manual skill mounts under the plugin's own name — that is what
    # makes `.library/intrinsic/capabilities/mcp/SKILL.md` a copy of a skill the
    # plugin owns rather than a file a convention happened to place there.
    assert plan["mounts"] == [("mcp", str(_MCP_PACKAGE / "skills" / "mcp-manual"))]


def test_a_package_without_a_manifest_is_left_to_the_legacy_convention(tmp_path):
    plan, problems = discover_tool_plugin(tmp_path)
    assert (plan, problems) == (None, [])


def test_a_rejected_manifest_mounts_nothing_and_explains_why(tmp_path):
    root = tmp_path / "broken"
    (root / "skills" / "broken-manual").mkdir(parents=True)
    (root / "skills" / "broken-manual" / "SKILL.md").write_text("body", encoding="utf-8")
    (root / "plugin.json").write_text(json.dumps({"name": "broken"}), encoding="utf-8")

    plan, problems = discover_tool_plugin(root)

    assert plan is None
    assert len(problems) == 1
    assert "$schema" in problems[0]["error"]


def test_discovery_flags_a_tool_plugin_that_smuggles_in_mcp_servers(tmp_path):
    """A tool package is not a second route into the MCP registry."""
    root = tmp_path / "smuggler"
    (root / "skills" / "smuggler-manual").mkdir(parents=True)
    (root / "skills" / "smuggler-manual" / "SKILL.md").write_text(
        "---\nname: smuggler-manual\ndescription: x\n---\nbody\n", encoding="utf-8"
    )
    (root / "plugin.json").write_text(
        json.dumps({
            "$schema": plugin_registry.PLUGIN_SCHEMA_URL,
            "name": "smuggler",
            "extensions": {
                "ai.lingtai.tool": {
                    "package": "nowhere",
                    "manual_skill": "smuggler-manual",
                }
            },
        }),
        encoding="utf-8",
    )
    (root / "mcp.json").write_text(
        json.dumps({
            "$schema": plugin_registry.MCP_SCHEMA_URL,
            "mcpServers": {"evil": {"type": "stdio", "command": "/bin/sh"}},
        }),
        encoding="utf-8",
    )

    plan, problems = discover_tool_plugin(root)

    assert plan["mounts"] == [
        ("smuggler", str(root / "skills" / "smuggler-manual"))
    ]
    assert any("must not carry mcp.json" in p["error"] for p in problems)
    # The plan carries a mount list and nothing else — there is no registry
    # write for a smuggled server to reach.
    assert set(plan) == {"name", "version", "manual_skill", "source", "mounts"}


def test_a_manual_skill_the_manifest_names_but_does_not_own_is_reported(tmp_path):
    root = tmp_path / "missing"
    (root / "skills").mkdir(parents=True)
    (root / "plugin.json").write_text(
        json.dumps({
            "$schema": plugin_registry.PLUGIN_SCHEMA_URL,
            "name": "missing",
            "extensions": {
                "ai.lingtai.tool": {"package": "nowhere", "manual_skill": "absent"}
            },
        }),
        encoding="utf-8",
    )

    plan, problems = discover_tool_plugin(root)

    assert plan["mounts"] == []
    assert any("not an owned skill" in p["error"] for p in problems)


# ---------------------------------------------------------------------------
# The runtime actually mounts it
# ---------------------------------------------------------------------------

def test_agent_boot_mounts_the_owned_skill_byte_for_byte(mcp_agent):
    _agent, workdir = mcp_agent
    mounted = workdir / ".library" / "intrinsic" / "capabilities" / "mcp"

    assert mounted.is_dir()
    assert (mounted / "SKILL.md").read_text(encoding="utf-8") == (
        MCP_TOOL_PLUGIN.skill_path.read_text(encoding="utf-8")
    )
    # The sidecars the skill routes to come along, so the mounted copy is the
    # whole skill and not just its router file.
    for sidecar in (
        "reference/curated-addons.md",
        "reference/third-party-and-legacy.md",
        "reference/troubleshooting.md",
        "scripts/find_readme.py",
    ):
        assert (mounted / sidecar).is_file(), sidecar


def test_manual_action_serves_the_mounted_owned_skill(mcp_agent):
    agent, workdir = mcp_agent
    result = agent._tool_handlers["mcp"](
        {"action": "manual", "input": {}, "reasoning": "load mcp guidance"}
    )

    mounted = workdir / ".library" / "intrinsic" / "capabilities" / "mcp" / "SKILL.md"
    assert result["status"] == "ok"
    assert result["manual_path"] == str(mounted)
    assert result["mcp_manual"] == MCP_TOOL_PLUGIN.skill_path.read_text(encoding="utf-8")


def test_mounting_a_tool_plugin_writes_no_plugin_owned_registry_record(mcp_agent):
    """Registration and activation boundaries survive the conversion."""
    _agent, workdir = mcp_agent
    registry = workdir / "mcp_registry.jsonl"

    lines = (
        registry.read_text(encoding="utf-8").splitlines() if registry.is_file() else []
    )
    for line in lines:
        if not line.strip():
            continue
        assert json.loads(line).get("source") != plugin_registry.plugin_source("mcp")


def test_the_tool_plugin_is_not_a_declared_or_discovered_agent_plugin(mcp_agent):
    """It ships inside the wheel; it is not installed on a plugin path."""
    agent, _workdir = mcp_agent
    snapshot = getattr(agent, "_plugin_registration", None) or {}
    names = {p.get("name") for p in snapshot.get("plugins", []) or []}
    assert "mcp" not in names


# ---------------------------------------------------------------------------
# The public surface is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_action_surface_is_unchanged():
    schema = get_schema()
    assert schema["properties"]["action"]["enum"] == list(MCP_ACTIONS)
    assert schema["required"] == ["action", "input", "reasoning"]
    assert [b["title"] for b in schema["properties"]["input"]["oneOf"]] == [
        "info input",
        "manual input",
    ]

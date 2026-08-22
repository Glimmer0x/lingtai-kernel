"""Built-in tool plugin packaging invariants, proven on the ``web`` reference slice.

A built-in tool is a plugin-style package: the same folder ships the tool code,
the ``manual/`` skill it owns, and the ``plugin.json`` manifest the host reads
to discover and mount it. ``lingtai.tools._plugin.ToolPlugin`` binds those three
and owns the one promise a package must not be able to break — the reserved
``manual`` action, appended from the packaged bundle rather than declared by the
package.

These tests pin the packaging promise, the *runtime* half of it (the manual
mount and the capability module resolution both follow the shipped manifest,
not a host-side table), and the **unchanged** public ``web`` surface around it:
same schema, same actions, same provider admission and security boundaries.
They make no network call and construct no provider: every path exercised here
is refused, composed, or served from disk before any search or fetch happens.
"""
from __future__ import annotations

import fnmatch
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from lingtai.agent import _LEGACY_MANUAL_DESTINATIONS, Agent
from lingtai.tools import _plugin, registry
from lingtai.tools._plugin import ToolPlugin, ToolPluginError
from lingtai.tools.registry import BUILTIN_TOOLS
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA
from lingtai.tools.web_search import RetiredProviderError, SettingsOnlyProviderError, setup
from lingtai.tools.web_search.plugin import WEB_ACTIONS, WEB_DECLARED_ACTIONS, WEB_PLUGIN

_REPO_ROOT = Path(__file__).resolve().parents[1]
_PACKAGE_DIR = _REPO_ROOT / "src/lingtai/tools/web_search"

_DESCRIPTOR_FIELDS = {
    "name": "web",
    "package": "lingtai.tools.web_search",
    "summary": "s",
    "homepage": "h",
    "skill_name": "web-manual",
    "declared_actions": ("search", "browse"),
}


class _Agent:
    """The minimal duck type ``web`` composes against (see test_unified_web_capability)."""

    def __init__(self, root: Path) -> None:
        self._working_dir = root
        self.tool_name: str | None = None

    def add_tool(self, *args, **kwargs) -> None:
        self.tool_name = args[0]
        self.schema = kwargs["schema"]
        self.handler = kwargs["handler"]


class _MountAgent:
    """The minimal duck type ``Agent._install_intrinsic_manuals`` runs against."""

    def __init__(self, root: Path) -> None:
        self._working_dir = root
        self._capabilities: list = []
        self.logs: list[tuple[str, dict]] = []

    def _log(self, event: str, **fields) -> None:
        self.logs.append((event, fields))


@pytest.fixture
def mounted(tmp_path) -> _MountAgent:
    """Run the real manual installer once into a scratch working directory."""
    agent = _MountAgent(tmp_path)
    Agent._install_intrinsic_manuals(agent)
    return agent


# ---------------------------------------------------------------------------
# The package ships its own manifest
# ---------------------------------------------------------------------------

def test_web_package_manifest_matches_the_shipped_plugin_json():
    """The package owns its declaration; ``plugin.json`` publishes exactly it."""
    shipped = json.loads(
        (_PACKAGE_DIR / _plugin.MANIFEST_FILENAME).read_text(encoding="utf-8")
    )
    assert shipped == WEB_PLUGIN.tool_declaration()


def test_manifest_declares_the_declaring_package_and_validates_as_a_record():
    declaration = WEB_PLUGIN.tool_declaration()
    assert declaration["schema"] == _plugin.TOOL_PLUGIN_SCHEMA
    assert declaration["source"] == _plugin.BUILTIN_SOURCE
    assert declaration["module"] == "lingtai.tools.web_search"
    assert declaration["manual"] == {
        "skill": "web-manual",
        "bundle": _plugin.MANUAL_BUNDLE_DIRNAME,
        # The public name, not the retained implementation directory — the fact
        # the host used to hardcode.
        "install_as": "web",
    }
    assert declaration["actions"] == ["search", "browse", "manual"]
    validated, error = _plugin.validate_manifest(declaration, directory_name="web_search")
    assert error is None and validated == declaration


def test_discovery_finds_the_shipped_manifest_from_disk():
    manifests, problems = _plugin.discover_manifests()
    assert problems == []
    assert manifests["web_search"] == WEB_PLUGIN.tool_declaration()


def test_discovery_does_not_import_the_tool_package_it_discovers():
    """Discovery is filesystem-only; ``registry.py``'s import discipline holds."""
    probe = (
        "import sys;"
        "from lingtai.tools.registry import plugin_module_path;"
        "path = plugin_module_path('web');"
        "print(path, 'lingtai.tools.web_search' in sys.modules)"
    )
    # Pin the interpreter at *this* worktree's ``src`` (pytest's own
    # ``pythonpath`` setting), so the probe cannot silently import an ambient
    # installed ``lingtai`` from somewhere else.
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(_REPO_ROOT / "src"), env.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "lingtai.tools.web_search False"


def test_shipped_manifest_reaches_the_wheel_through_the_tools_package_data_glob():
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    globs = config["tool"]["setuptools"]["package-data"]["lingtai.tools"]
    relative = f"web_search/{_plugin.MANIFEST_FILENAME}"
    assert any(fnmatch.fnmatch(relative, pattern) for pattern in globs)


# ---------------------------------------------------------------------------
# Runtime mount 1 — the capability module resolves through the manifest
# ---------------------------------------------------------------------------

def test_registry_entry_and_shipped_manifest_name_one_module():
    assert registry.plugin_module_path("web") == BUILTIN_TOOLS["web"]


def test_setup_capability_mounts_the_module_the_manifest_publishes(tmp_path):
    agent = _Agent(tmp_path)
    manager = registry.setup_capability(agent, "web", search_service=object())
    assert agent.tool_name == WEB_PLUGIN.name == "web"
    assert type(manager).__module__ == registry.plugin_module_path("web")


def test_setup_capability_refuses_a_registry_manifest_disagreement(tmp_path, monkeypatch):
    """Two descriptions of the same tool is a packaging defect, not a preference."""
    monkeypatch.setitem(BUILTIN_TOOLS, "web", "lingtai.tools.vision")
    with pytest.raises(ToolPluginError, match="shipped plugin manifest declares"):
        registry.setup_capability(_Agent(tmp_path), "web")


# ---------------------------------------------------------------------------
# Runtime mount 2 — the manual bundle mounts where the manifest says
# ---------------------------------------------------------------------------

def test_web_is_no_longer_a_host_side_special_case():
    assert _LEGACY_MANUAL_DESTINATIONS == {"bash": "shell"}
    assert "web_search" not in _LEGACY_MANUAL_DESTINATIONS


def test_manual_bundle_mounts_under_the_public_name_the_manifest_declares(mounted):
    capabilities = mounted._working_dir / ".library/intrinsic/capabilities"
    mounted_skill = capabilities / "web" / "SKILL.md"
    assert mounted_skill.is_file()
    assert not (capabilities / "web_search").exists()
    # The mounted copy is this plugin's own packaged bundle, byte for byte.
    assert mounted_skill.read_text(encoding="utf-8") == (
        Path(WEB_PLUGIN.skill_path).read_text(encoding="utf-8")
    )
    assert WEB_PLUGIN.skill_frontmatter["name"] == "web-manual"
    assert WEB_PLUGIN.read_skill_body().strip()
    # Sidecars ship with the bundle, exactly as before.
    assert (capabilities / "web/reference/tier-0-pdf.md").is_file()
    assert (capabilities / "web/scripts/extract_page.py").is_file()
    # A non-plugin retained directory still uses the host's legacy mapping.
    assert (capabilities / "shell/SKILL.md").is_file()


def test_the_mount_follows_the_manifest_rather_than_a_hardcoded_destination(
    tmp_path, monkeypatch
):
    """Change the manifest's declared destination and the mount moves with it."""
    relocated = json.loads(json.dumps(WEB_PLUGIN.tool_declaration()))
    relocated["manual"]["install_as"] = "web-relocated"
    monkeypatch.setattr(
        _plugin, "discover_manifests", lambda root=None: ({"web_search": relocated}, [])
    )
    agent = _MountAgent(tmp_path)
    Agent._install_intrinsic_manuals(agent)
    capabilities = tmp_path / ".library/intrinsic/capabilities"
    assert (capabilities / "web-relocated/SKILL.md").is_file()
    assert not (capabilities / "web").exists()


def test_an_unusable_manifest_is_reported_and_never_half_applied(tmp_path, monkeypatch):
    monkeypatch.setattr(
        _plugin,
        "discover_manifests",
        lambda root=None: ({}, [{"package": "web_search", "reason": "boom"}]),
    )
    agent = _MountAgent(tmp_path)
    Agent._install_intrinsic_manuals(agent)
    assert ("tool_plugin_manifest_invalid", {"package": "web_search", "reason": "boom"}) in agent.logs
    # Fell back to the pre-plugin rule (own directory name) rather than
    # guessing a public name the host was never told.
    capabilities = tmp_path / ".library/intrinsic/capabilities"
    assert (capabilities / "web_search/SKILL.md").is_file()


@pytest.mark.parametrize(
    "mutate, reason",
    [
        pytest.param(lambda m: m.__setitem__("schema", "other"), "schema", id="schema"),
        pytest.param(lambda m: m.__setitem__("source", "plugin:web"), "source", id="source"),
        pytest.param(
            lambda m: m.__setitem__("module", "lingtai.tools.vision"), "package it ships in", id="module"
        ),
        pytest.param(
            lambda m: m["manual"].__setitem__("bundle", "../elsewhere"),
            "plain directory name",
            id="bundle-escape",
        ),
        pytest.param(
            lambda m: m["manual"].__setitem__("install_as", "../web"),
            "plain capability name",
            id="install-escape",
        ),
        pytest.param(
            lambda m: m.__setitem__("actions", ["manual", "search"]), "must end with", id="actions"
        ),
    ],
)
def test_a_manifest_the_host_cannot_trust_is_rejected_with_a_reason(mutate, reason):
    manifest = json.loads(json.dumps(WEB_PLUGIN.tool_declaration()))
    mutate(manifest)
    validated, error = _plugin.validate_manifest(manifest, directory_name="web_search")
    assert validated is None
    assert reason in error


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the packaged skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in WEB_DECLARED_ACTIONS
    assert WEB_DECLARED_ACTIONS == ("search", "browse")
    assert WEB_ACTIONS == (*WEB_DECLARED_ACTIONS, "manual")
    assert WEB_ACTIONS[-1] == "manual"


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(
            lambda: WEB_PLUGIN.action_input_schemas({"search": {}, "manual": {}}),
            id="schemas",
        ),
        pytest.param(
            lambda: WEB_PLUGIN.build_family(
                [
                    ChildTool("search", {"type": "object"}, lambda _i: {}),
                    ChildTool("browse", {"type": "object"}, lambda _i: {}),
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


def test_a_package_cannot_compose_a_family_that_disagrees_with_its_declaration():
    with pytest.raises(ToolPluginError, match="single source of truth"):
        WEB_PLUGIN.build_family([ChildTool("search", {"type": "object"}, lambda _i: {})])


def test_composed_family_always_carries_a_manual_child_with_the_owned_input(tmp_path):
    manager = setup(_Agent(tmp_path), search_service=object())
    assert manager._family.child_names == WEB_ACTIONS
    assert manager._family.has_manual()
    assert WEB_PLUGIN.action_input_schemas({"search": {}, "browse": {}})["manual"] == (
        MANUAL_INPUT_SCHEMA
    )


def test_manual_answers_from_the_mounted_copy_of_the_packaged_skill(mounted):
    manager = setup(_Agent(mounted._working_dir), search_service=object())
    result = manager.handle({"action": "manual", "input": {}})
    assert result["status"] == "ok"
    assert result["action"] == "manual"
    # Web's pre-migration flat public shape is unchanged: the model-visible
    # ``manual_path`` is the host-local mount, not the site-packages original.
    expected_mount = (
        mounted._working_dir / ".library/intrinsic/capabilities/web/SKILL.md"
    )
    assert result["manual_path"] == str(expected_mount)
    assert result["manual"] == expected_mount.read_text(encoding="utf-8")
    assert set(result) == {"status", "manual", "manual_path", "action", "current_setting"}


def test_manual_reads_no_settings_and_touches_no_provider(mounted):
    """Packaging did not move ``manual`` onto the search path."""
    (mounted._working_dir / "settings").mkdir(exist_ok=True)
    (mounted._working_dir / "settings/web.search.json").write_text("{ broken", encoding="utf-8")
    manager = setup(_Agent(mounted._working_dir), search_service=object())
    result = manager.handle({"action": "manual", "input": {}})
    assert result["status"] == "ok"
    assert result["current_setting"]["settings_revision"] == "not_read"


# ---------------------------------------------------------------------------
# The public `web` surface is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_action_family_shape(tmp_path):
    agent = _Agent(tmp_path)
    setup(agent, search_service=object())
    schema = agent.schema
    assert schema["properties"]["action"]["enum"] == list(WEB_ACTIONS)
    assert len(schema["allOf"]) == len(WEB_ACTIONS)
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    assert branch_titles == ["search input", "browse input", "manual input"]


def test_action_required_message_still_lists_the_public_actions(tmp_path):
    manager = setup(_Agent(tmp_path), search_service=object())
    result = manager.handle({"input": {}})
    assert result["error_code"] == "ACTION_REQUIRED"
    assert result["action"] == "unknown"
    assert result["message"] == "action must be one of search, browse, or manual"


def test_search_and_browse_still_dispatch_to_their_own_handlers(tmp_path):
    class _Search:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def search(self, query: str, max_results: int | None = None):
            self.calls.append(query)
            return []

    search = _Search()
    manager = setup(_Agent(tmp_path), search_service=search)
    result = manager.handle({"action": "search", "input": {"query": "question"}})
    assert result["status"] == "ok" and result["action"] == "search"
    assert search.calls == ["question"]


# ---------------------------------------------------------------------------
# Provider / security boundaries are untouched by the packaging
# ---------------------------------------------------------------------------

def test_provider_admission_and_the_settings_only_opt_in_are_unchanged(tmp_path):
    from lingtai.tools.web_search import PROVIDERS

    assert PROVIDERS == {
        "providers": ["duckduckgo", "gemini", "anthropic", "openai"],
        "default": "duckduckgo",
        "fallback_on_inherit": "duckduckgo",
    }
    with pytest.raises(RetiredProviderError):
        setup(_Agent(tmp_path), provider="minimax")
    with pytest.raises(SettingsOnlyProviderError):
        setup(_Agent(tmp_path), provider="anthropic")


def test_a_settings_gated_engine_still_fails_before_any_provider_is_built(tmp_path):
    (tmp_path / "settings").mkdir()
    (tmp_path / "settings/web.search.json").write_text(
        json.dumps({"schema_version": 1, "engine": "anthropic"}), encoding="utf-8"
    )
    manager = setup(_Agent(tmp_path))
    result = manager.handle({"action": "search", "input": {"query": "q"}})
    assert result["status"] == "failed"
    assert result["error_code"] == "PROVIDER_BACKEND_INELIGIBLE"


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_package_outside_lingtai_tools():
    with pytest.raises(ToolPluginError, match="immediate lingtai.tools subpackage"):
        ToolPlugin(**{**_DESCRIPTOR_FIELDS, "package": "lingtai.mcp_servers.telegram"})


def test_descriptor_rejects_a_manual_that_is_not_the_packaged_skill():
    with pytest.raises(ToolPluginError, match="declares name"):
        ToolPlugin(**{**_DESCRIPTOR_FIELDS, "skill_name": "somebody-elses-manual"})


def test_descriptor_rejects_a_package_with_no_packaged_manual_bundle():
    with pytest.raises(ToolPluginError, match="unreadable"):
        ToolPlugin(
            **{
                **_DESCRIPTOR_FIELDS,
                "name": "file",
                "package": "lingtai.tools.file",
                "declared_actions": ("read",),
            }
        )


def test_descriptor_rejects_declaring_the_reserved_manual():
    with pytest.raises(ToolPluginError, match="reserved 'manual'"):
        ToolPlugin(**{**_DESCRIPTOR_FIELDS, "declared_actions": ("search", "manual")})


def test_descriptor_rejects_duplicate_and_empty_action_lists():
    with pytest.raises(ToolPluginError, match="duplicate action"):
        ToolPlugin(**{**_DESCRIPTOR_FIELDS, "declared_actions": ("search", "search")})
    with pytest.raises(ToolPluginError, match="at least one action"):
        ToolPlugin(**{**_DESCRIPTOR_FIELDS, "declared_actions": ()})


@pytest.mark.parametrize("blank_field", ["name", "package", "summary", "homepage", "skill_name"])
def test_descriptor_rejects_blank_identity_fields(blank_field):
    with pytest.raises(ToolPluginError, match="non-empty string"):
        ToolPlugin(**{**_DESCRIPTOR_FIELDS, blank_field: "  "})

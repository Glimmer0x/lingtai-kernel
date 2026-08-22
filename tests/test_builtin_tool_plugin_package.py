"""Built-in tool plugin packaging invariants, proven on the Avatar reference slice.

A built-in tool is a plugin-style package: the same folder ships the tool code,
the bundled ``manual/SKILL.md``, and the capability declaration the tool
registry publishes. ``lingtai.tools._plugin.BuiltinToolPlugin`` binds those
three and owns the one promise a package must not be able to break — the
reserved ``manual`` action, appended from the packaged skill rather than
declared, schema'd, or handled by the package.

These tests pin the packaging promise, the runtime discovery/mount contract
around it (registry entry, lazy import, ``.library`` install), and the
*unchanged* public Avatar surface. The ``manual`` tests run against a real
host built by the ``host`` fixture — a real ``Agent`` whose real
``_install_intrinsic_manuals`` put the skill on disk — because the one thing
the action must report is the *host-local installed* path, which a hand-built
stub could only assert against itself. No test spawns a live avatar: the
launcher Port is a double, every agent lives under ``tmp_path``, and the
manual action touches nothing.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from lingtai.tools import _plugin, registry
from lingtai.tools import avatar as avatar_tool
from lingtai.tools._plugin import BuiltinToolPlugin, BuiltinToolPluginError
from lingtai.tools.avatar import AvatarManager
from lingtai.tools.avatar.plugin import (
    AVATAR_ACTIONS,
    AVATAR_DECLARED_ACTIONS,
    AVATAR_DESCRIPTION,
    AVATAR_PLUGIN,
)
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA

_REPO_ROOT = Path(__file__).resolve().parents[1]


class _RecordingManager:
    """Stands in for AvatarManager's handlers; records every action it is handed."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def handler(self, action: str):
        def _handle(action_input):
            self.calls.append((action, dict(action_input)))
            return {"status": "ok", "action": action}

        return _handle


def _recording_family(recorder: _RecordingManager, agent=None):
    """Avatar's real family with its declared actions bound to the recorder."""
    return avatar_tool._build_family(
        {action: recorder.handler(action) for action in AVATAR_DECLARED_ACTIONS},
        agent,
    )


@pytest.fixture
def host(tmp_path):
    """A real agent host, manuals installed by the real installer.

    ``Agent.__init__`` runs ``_install_intrinsic_manuals``, so the avatar skill
    is on disk at ``AVATAR_PLUGIN.installed_manual_path()`` exactly as a booted
    agent sees it. No live avatar is ever spawned: nothing here calls ``spawn``.
    """
    from lingtai.agent import Agent
    from tests._service_helpers import make_gemini_mock_service

    return Agent(
        service=make_gemini_mock_service(),
        agent_name="parent",
        working_dir=tmp_path / "parent",
        capabilities=["avatar"],
    )


def _installed_manual(agent) -> Path:
    return agent._working_dir / AVATAR_PLUGIN.installed_manual_path()


def _descriptor_fields(**overrides):
    fields = {
        "name": "avatar",
        "package": "lingtai.tools.avatar",
        "summary": "s",
        "skill_name": "avatar-manual",
    }
    fields.update(overrides)
    return fields


# ---------------------------------------------------------------------------
# The package ships its own capability declaration
# ---------------------------------------------------------------------------

def test_avatar_package_declaration_matches_the_shipped_registry_entries():
    """The package owns its module path and boot kwargs; the registry publishes exactly them."""
    declaration = AVATAR_PLUGIN.capability_declaration()
    assert registry.BUILTIN_TOOLS[declaration["name"]] == declaration["module"]
    assert registry.CORE_DEFAULTS[declaration["name"]] == declaration["default_kwargs"]
    assert declaration["source"] == _plugin.BUILTIN_SOURCE


def test_declaration_imports_the_declaring_package_and_still_boots_through_the_host():
    declaration = AVATAR_PLUGIN.capability_declaration()
    assert declaration["module"] == AVATAR_PLUGIN.package == avatar_tool.__name__
    # The host's own resolution path — unchanged — still finds this capability.
    assert registry.canonical_capability_name("avatar") == "avatar"
    assert "avatar" in registry.get_all_providers()
    # And the always-on floor materializes exactly the declared kwargs.
    assert registry.apply_core_defaults({})["avatar"] == declaration["default_kwargs"]


def test_registry_lookup_is_unchanged_and_still_the_runtime_source():
    """The descriptor documents the entry; it does not replace registry lookup.

    Importing the registry must still not import this package — the descriptor
    lives inside ``lingtai.tools.avatar``, so a registry that consulted it at
    import time would break the lazy-capability-import discipline the registry
    docstring promises.
    """
    probe = (
        "import sys, lingtai.tools.registry as r;"
        "assert 'lingtai.tools.avatar' not in sys.modules, 'registry eagerly imported avatar';"
        "assert 'lingtai.tools.avatar.plugin' not in sys.modules;"
        "print(r.BUILTIN_TOOLS['avatar'])"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(_REPO_ROOT / "src")},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "lingtai.tools.avatar"


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and sourced from the packaged skill
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in AVATAR_DECLARED_ACTIONS
    assert AVATAR_ACTIONS == (*AVATAR_DECLARED_ACTIONS, "manual")
    assert AVATAR_ACTIONS[-1] == "manual"
    assert [name for name, _schema in avatar_tool._DECLARED_CHILD_SPECS] == list(
        AVATAR_DECLARED_ACTIONS
    )


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: AVATAR_PLUGIN.actions(["spawn", "manual"]), id="actions"),
        pytest.param(
            lambda: AVATAR_PLUGIN.child_specs(
                [("spawn", {"type": "object"}), ("manual", {"type": "object"})]
            ),
            id="specs",
        ),
        pytest.param(
            lambda: AVATAR_PLUGIN.build_family(
                [
                    ChildTool("spawn", {"type": "object"}, lambda _i: {}),
                    ChildTool("manual", {"type": "object"}, lambda _i: {"hijacked": True}),
                ],
                None,
            ),
            id="family",
        ),
    ],
)
def test_a_package_cannot_declare_re_schema_or_rebind_the_reserved_manual(compose):
    with pytest.raises(BuiltinToolPluginError, match="reserved 'manual'"):
        compose()


def test_composed_family_always_carries_a_manual_child_with_the_shared_strict_input():
    family = _recording_family(_RecordingManager())
    assert family.has_manual()
    assert family.child_names == AVATAR_ACTIONS
    # The one owned strict-empty schema object, not a restatement of it.
    assert dict(avatar_tool._CHILD_SPECS)["manual"] is MANUAL_INPUT_SCHEMA


def test_manual_answers_from_the_installed_skill_without_entering_the_manager(host):
    recorder = _RecordingManager()
    family = _recording_family(recorder, host)
    result = family.handle({"action": "manual", "input": {}})
    assert recorder.calls == []
    assert result == AVATAR_PLUGIN.manual_payload(host)
    assert result["status"] == "ok"
    assert result["action"] == "manual"
    skill_path = Path(result["manual_path"])
    assert skill_path == _installed_manual(host)
    assert result["manual"] == skill_path.read_text(encoding="utf-8")


def test_manual_reports_the_host_local_install_not_the_packaged_source(host):
    """The regression: ``manual_path`` is the agent's own file, never the source tree.

    A real host, a real ``_install_intrinsic_manuals``, and the real
    ``AvatarManager.handle`` dispatch — the path the model is handed must be
    openable from inside this agent's working dir.
    """
    installed = _installed_manual(host)
    assert installed.is_file()

    manager = AvatarManager(host, launcher=object())
    result = manager.handle({"action": "manual", "input": {}})

    assert result["status"] == "ok"
    assert result["action"] == "manual"
    assert Path(result["manual_path"]) == installed
    assert result["manual"] == installed.read_text(encoding="utf-8")
    # Not the candidate/source copy the host installed *from*.
    packaged = Path(str(AVATAR_PLUGIN.manual_resource()))
    assert Path(result["manual_path"]) != packaged
    assert host._working_dir in Path(result["manual_path"]).parents


def test_manual_degrades_truthfully_when_the_host_has_no_installed_copy(host):
    """A failed install is reported, never backfilled from the packaged source."""
    installed = _installed_manual(host)
    installed.unlink()

    result = AvatarManager(host, launcher=object()).handle(
        {"action": "manual", "input": {}}
    )
    assert result["status"] == "degraded"
    assert result["action"] == "manual"
    assert result["manual"] == ""
    assert "avatar manual missing" in result["error"]
    assert Path(result["manual_path"]) == installed


def test_the_manager_cannot_rebind_the_public_manual_action(host):
    """Even a manager that redefines its own manual cannot change the action."""

    class _HijackingManager(AvatarManager):
        def _manual(self):
            return {"status": "ok", "action": "manual", "manual": "hijacked"}

    manager = _HijackingManager(host, launcher=object())

    result = manager.handle({"action": "manual", "input": {}})
    assert result == AVATAR_PLUGIN.manual_payload(host)
    assert result["manual"] != "hijacked"


def test_manual_payload_is_the_same_document_the_legacy_manager_helper_returns(host):
    """Routing manual through the plugin preserves the existing public result."""
    bare = object.__new__(AvatarManager)
    bare._agent = host
    assert bare._manual() == AVATAR_PLUGIN.manual_payload(host)


def test_manual_input_stays_strictly_empty_and_the_action_writes_nothing(host, tmp_path):
    recorder = _RecordingManager()
    family = _recording_family(recorder, host)
    rejected = family.handle({"action": "manual", "input": {"name": "helper"}})
    assert rejected["status"] == "failed"
    assert rejected["error_code"] == "INVALID_ARGUMENT"
    assert recorder.calls == []
    # The accepted call is read-only: nothing is created anywhere.
    before = sorted(p.name for p in tmp_path.iterdir())
    assert family.handle({"action": "manual", "input": {}})["status"] == "ok"
    assert sorted(p.name for p in tmp_path.iterdir()) == before


# ---------------------------------------------------------------------------
# The packaged skill is this plugin's owned skill, installed where it says
# ---------------------------------------------------------------------------

def test_the_packaged_manual_is_the_declared_owned_skill():
    AVATAR_PLUGIN.validate_packaged_skill()
    packaged = Path(str(AVATAR_PLUGIN.manual_resource()))
    assert packaged == _REPO_ROOT / "src/lingtai/tools/avatar/manual/SKILL.md"
    assert f"name: {AVATAR_PLUGIN.skill_name}" in packaged.read_text(encoding="utf-8")


def test_a_foreign_or_missing_packaged_skill_degrades_and_validates_loudly():
    foreign = BuiltinToolPlugin(**_descriptor_fields(skill_name="somebody-elses-manual"))
    loaded = foreign.load_manual()
    assert loaded["status"] == "degraded"
    # Refused, not served: the body is empty and the error names the mismatch.
    assert loaded["manual"] == ""
    assert "expected 'somebody-elses-manual'" in loaded["error"]
    assert foreign.load_manual()["manual_path"].endswith("SKILL.md")
    with pytest.raises(BuiltinToolPluginError, match="declares skill"):
        foreign.validate_packaged_skill()


def test_the_host_installs_the_packaged_skill_where_the_descriptor_says(host):
    """``Agent._install_intrinsic_manuals`` is the mount; the descriptor names it."""
    installed = _installed_manual(host)
    assert installed.is_file()
    # Installed verbatim from the packaged source the descriptor points at.
    packaged = Path(str(AVATAR_PLUGIN.manual_resource()))
    assert installed.read_text(encoding="utf-8") == packaged.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The public envelope and mount are unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_action_family_shape():
    schema = avatar_tool.get_schema()
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == list(AVATAR_ACTIONS)
    assert len(schema["allOf"]) == len(AVATAR_ACTIONS)
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    assert branch_titles == [f"{action} input" for action in AVATAR_ACTIONS]


def test_unknown_action_error_names_exactly_the_plugin_action_list():
    bare = object.__new__(AvatarManager)
    bare._family = avatar_tool._FAMILY
    bare._pending_reasoning = None
    assert bare.handle({"action": "bogus", "input": {}}) == {
        "error": "unknown action: 'bogus', only 'spawn', 'rules', or 'manual' is supported",
    }
    assert avatar_tool._SUPPORTED_ACTIONS_PHRASE == "'spawn', 'rules', or 'manual'"


def test_declared_actions_still_dispatch_into_their_own_handlers():
    recorder = _RecordingManager()
    family = _recording_family(recorder)
    result = family.handle(
        {"action": "rules", "input": {"rules_content": "Be concise."}}
    )
    assert result == {"status": "ok", "action": "rules"}
    assert recorder.calls == [("rules", {"rules_content": "Be concise."})]


def test_setup_mounts_one_tool_sourced_from_the_plugin_descriptor():
    from unittest.mock import MagicMock

    agent = MagicMock()
    avatar_tool.setup(agent)
    assert agent.add_tool.call_count == 1
    (name,), kwargs = agent.add_tool.call_args
    assert name == AVATAR_PLUGIN.name == "avatar"
    assert kwargs["glossary_package"] == AVATAR_PLUGIN.package
    assert kwargs["description"] == AVATAR_DESCRIPTION
    assert kwargs["schema"] == avatar_tool.get_schema()
    # Composition only: the descriptor hands back kwargs, the package calls.
    assert set(kwargs) == {"schema", "handler", "description", "glossary_package"}


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_package_that_is_not_its_own_module():
    with pytest.raises(BuiltinToolPluginError, match="must be the 'avatar' module"):
        BuiltinToolPlugin(**_descriptor_fields(package="lingtai.tools.daemon"))


def test_descriptor_rejects_a_package_outside_the_builtin_tool_tree():
    with pytest.raises(BuiltinToolPluginError, match="must live under 'lingtai.tools.'"):
        BuiltinToolPlugin(**_descriptor_fields(package="lingtai.mcp_servers.avatar"))


def test_descriptor_accepts_a_retained_implementation_directory_alias():
    """``bash``→``shell`` style renames declare the module, never the destination."""
    aliased = BuiltinToolPlugin(
        name="shell",
        package="lingtai.tools.bash",
        summary="s",
        skill_name="shell-manual",
        module_name="bash",
    )
    assert aliased.module == "bash"
    assert aliased.capability_declaration()["module"] == "lingtai.tools.bash"
    assert aliased.installed_manual_path() == ".library/intrinsic/capabilities/shell/SKILL.md"


@pytest.mark.parametrize("blank_field", ["name", "package", "summary", "skill_name"])
def test_descriptor_rejects_blank_identity_fields(blank_field):
    with pytest.raises(BuiltinToolPluginError, match="non-empty string"):
        BuiltinToolPlugin(**_descriptor_fields(**{blank_field: "  "}))


def test_descriptor_rejects_non_mapping_boot_kwargs():
    with pytest.raises(BuiltinToolPluginError, match="must be a mapping"):
        BuiltinToolPlugin(**_descriptor_fields(default_kwargs=["yolo"]))

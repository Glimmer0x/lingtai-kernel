"""Built-in tool plugin packaging invariants, proven on the Daemon reference slice.

A built-in capability tool is a plugin-style package: the same folder ships the
handler code, the bundled ``manual/`` skill the initializer mounts into the
agent's own ``.library``, and the capability record the host registry publishes.
``lingtai.tools._plugin.BuiltinToolPlugin`` binds those three and owns the one
promise a package must not be able to break — the reserved ``manual`` action,
appended from the packaged skill rather than declared by the package.

These tests pin the packaging promise, the runtime discovery/mount contract the
descriptor states, and the *unchanged* public Daemon surface around it. They
start no emanation, spawn no process, and write no run directory: every daemon
action here either stops at the family's dispatch boundary or lands on a
recording stand-in for ``DaemonManager``.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests._daemon_helpers import make_daemon_agent
from lingtai.tools import _plugin
from lingtai.tools._plugin import BuiltinToolPlugin, BuiltinToolPluginError
from lingtai.tools import daemon as daemon_pkg
from lingtai.tools.daemon import _tool_family
from lingtai.tools.daemon.plugin import (
    DAEMON_ACTIONS,
    DAEMON_DECLARED_ACTIONS,
    DAEMON_PLUGIN,
)
from lingtai.tools.registry import BUILTIN_TOOLS, CORE_DEFAULTS, setup_capability
from lingtai.tools.tool_family import ChildTool
from lingtai.tools.tool_family.manual import MANUAL_INPUT_SCHEMA

_REPO_ROOT = Path(__file__).resolve().parents[1]

_VALID_FIELDS = {
    "name": "daemon",
    "package": "lingtai.tools.daemon",
    "implementation": "daemon",
    "summary": "s",
    "manual_skill_name": "daemon-manual",
}


class _RecordingManager:
    """Stands in for ``DaemonManager``; records every flat action it is handed."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def handle(self, args: dict) -> dict:
        self.calls.append(dict(args))
        return {"status": "ok", "action": args.get("action")}


def _dispatcher(tmp_path: Path) -> tuple[_tool_family.DaemonFamilyDispatcher, _RecordingManager]:
    agent = MagicMock()
    agent._working_dir = tmp_path
    manager = _RecordingManager()
    return (
        _tool_family.DaemonFamilyDispatcher(
            manager, agent, list(daemon_pkg._BACKEND_SCHEMA_ENUM)
        ),
        manager,
    )


# ---------------------------------------------------------------------------
# The package ships its own capability declaration
# ---------------------------------------------------------------------------

def test_daemon_package_declaration_matches_the_shipped_capability_registry():
    """The package owns its module path; BUILTIN_TOOLS publishes exactly it."""
    declaration = DAEMON_PLUGIN.capability_declaration()
    assert BUILTIN_TOOLS[declaration["name"]] == declaration["module"]
    assert declaration["module"] == "lingtai.tools.daemon"
    assert declaration["source"] == _plugin.BUILTIN_SOURCE
    # Daemon is part of the always-on floor; the descriptor names the same key.
    assert declaration["name"] in CORE_DEFAULTS


def test_registry_loading_is_unchanged_and_still_the_runtime_source(tmp_path):
    """The descriptor documents the record; it does not replace capability setup."""
    agent = MagicMock()
    agent._working_dir = tmp_path
    manager = setup_capability(agent, DAEMON_PLUGIN.name)
    assert isinstance(manager, daemon_pkg.DaemonManager)
    registered = agent.add_tool.call_args
    assert registered.args[0] == DAEMON_PLUGIN.name == "daemon"
    assert registered.kwargs["schema"]["properties"]["action"]["enum"] == list(
        DAEMON_ACTIONS
    )


def test_the_descriptor_is_declarative_and_imports_no_runtime(tmp_path):
    """``_plugin`` is packaging, not a plugin runtime: it discovers nothing.

    Importing it must not drag in the daemon engine, the agent, or the
    capability registry — the same import discipline ``lingtai.tools`` owes
    the kernel. A descriptor that imported what it describes would be a
    discovery mechanism in disguise.
    """
    probe = (
        "import sys; import lingtai.tools._plugin as p; "
        "print(','.join(sorted(m for m in "
        "('lingtai.agent', 'lingtai.tools.daemon', 'lingtai.tools.registry') "
        "if m in sys.modules)))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=_REPO_ROOT,
        env={"PYTHONPATH": str(_REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    assert completed.stdout.strip() == ""


# ---------------------------------------------------------------------------
# Runtime discovery/mount contract: the packaged bundle and where it lands
# ---------------------------------------------------------------------------

def test_declared_manual_source_is_the_packages_own_bundle():
    source = _REPO_ROOT / DAEMON_PLUGIN.capability_declaration()["manual_source"]
    assert source.is_dir()
    skill = source / _plugin.SKILL_FILENAME
    assert skill.is_file()
    assert Path(DAEMON_PLUGIN.skill_path).resolve() == skill.resolve()
    assert DAEMON_PLUGIN.skill_frontmatter["name"] == "daemon-manual"


def test_the_initializer_mounts_the_packaged_bundle_at_the_declared_mount(tmp_path):
    """The real ``Agent`` install puts this package's skill exactly where the
    descriptor says the ``manual`` action will read it back from."""
    agent = make_daemon_agent(tmp_path, working_dir_name="mount-agent")
    mounted = agent._working_dir / DAEMON_PLUGIN.mounted_manual_relpath()
    assert mounted.is_file()
    assert mounted.read_text(encoding="utf-8") == (
        Path(DAEMON_PLUGIN.skill_path).read_text(encoding="utf-8")
    )
    assert DAEMON_PLUGIN.skill_body in mounted.read_text(encoding="utf-8")


def test_manual_answers_from_the_mounted_skill_without_entering_the_manager(tmp_path):
    agent = make_daemon_agent(tmp_path, working_dir_name="manual-agent")
    manager = _RecordingManager()
    dispatcher = _tool_family.DaemonFamilyDispatcher(
        manager, agent, list(daemon_pkg._BACKEND_SCHEMA_ENUM)
    )
    result = dispatcher.handle(
        {"action": "manual", "input": {}, "reasoning": "read the manual"}
    )
    assert manager.calls == []
    assert result["status"] == "ok"
    mounted = agent._working_dir / DAEMON_PLUGIN.mounted_manual_relpath()
    assert result["structuredContent"] == {"manual_path": str(mounted)}
    assert result["content"][0]["text"] == mounted.read_text(encoding="utf-8")
    assert DAEMON_PLUGIN.skill_body in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# `manual` is mandatory, reserved, and owned by the plugin
# ---------------------------------------------------------------------------

def test_package_does_not_declare_manual_and_the_plugin_appends_it_last():
    assert _plugin.MANUAL_ACTION not in DAEMON_DECLARED_ACTIONS
    assert DAEMON_ACTIONS == (*DAEMON_DECLARED_ACTIONS, "manual")
    assert DAEMON_ACTIONS[-1] == "manual"
    # The package's own child registry stops at its five declared actions.
    assert tuple(name for name, _ in _tool_family._declared_child_specs([])) == (
        DAEMON_DECLARED_ACTIONS
    )


@pytest.mark.parametrize(
    "compose",
    [
        pytest.param(lambda: DAEMON_PLUGIN.actions(["check", "manual"]), id="actions"),
        pytest.param(
            lambda: DAEMON_PLUGIN.action_input_schemas(
                (("check", {}), ("manual", {}))
            ),
            id="schemas",
        ),
        pytest.param(
            lambda: DAEMON_PLUGIN.build_family(
                [
                    ChildTool("check", {"type": "object"}, lambda _i: {}),
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


def test_a_package_must_declare_at_least_one_action_of_its_own():
    with pytest.raises(BuiltinToolPluginError, match="at least one action"):
        DAEMON_PLUGIN.actions([])


def test_composed_family_always_carries_a_manual_child_with_a_strict_empty_input(tmp_path):
    dispatcher, _ = _dispatcher(tmp_path)
    family = dispatcher._family
    assert family.child_names == DAEMON_ACTIONS
    assert dict(_tool_family._child_specs([]))["manual"] == MANUAL_INPUT_SCHEMA
    # A fresh copy per family: one tool's manual child cannot edit another's.
    assert DAEMON_PLUGIN.manual_input_schema() is not MANUAL_INPUT_SCHEMA
    assert DAEMON_PLUGIN.manual_input_schema() == MANUAL_INPUT_SCHEMA


def test_manual_lives_in_the_same_strict_root_as_every_other_action(tmp_path):
    """Plugin ownership does not buy ``manual`` a laxer envelope."""
    schema = daemon_pkg.get_schema()
    assert "manual" in schema["properties"]["action"]["enum"]
    assert schema["required"] == ["action", "input", "reasoning"]

    dispatcher, manager = _dispatcher(tmp_path)
    rejected = dispatcher.handle(
        {"action": "manual", "input": {"topic": "check"}, "reasoning": "x"}
    )
    assert rejected["status"] == "failed"
    assert manager.calls == []


# ---------------------------------------------------------------------------
# The public envelope shape is unchanged by the packaging
# ---------------------------------------------------------------------------

def test_public_schema_keeps_the_strict_action_family_shape():
    schema = daemon_pkg.get_schema()
    assert set(schema["properties"]) == {"action", "input", "reasoning", "summarize"}
    assert schema["required"] == ["action", "input", "reasoning"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["action"]["enum"] == list(DAEMON_ACTIONS)
    assert len(schema["allOf"]) == len(DAEMON_ACTIONS)
    branch_titles = [b["title"] for b in schema["properties"]["input"]["oneOf"]]
    assert branch_titles == [f"{action} input" for action in DAEMON_ACTIONS]


def test_declared_actions_still_dispatch_flat_into_the_engine(tmp_path):
    dispatcher, manager = _dispatcher(tmp_path)
    result = dispatcher.handle(
        {
            "action": "check",
            "input": {"id": "em-1", "last": None, "truncate": None},
            "reasoning": "probe",
        }
    )
    assert result["status"] == "ok"
    assert manager.calls == [{"action": "check", "id": "em-1"}]


def test_unknown_action_message_is_generated_from_the_declared_action_list(tmp_path):
    dispatcher, manager = _dispatcher(tmp_path)
    rejected = dispatcher.handle({"input": {}, "reasoning": "no action"})
    assert rejected["error_code"] == "ACTION_REQUIRED"
    assert rejected["message"] == (
        "action must be one of emanate, list, ask, check, reclaim, or manual"
    )
    assert manager.calls == []


# ---------------------------------------------------------------------------
# Descriptor defects fail loudly at import time
# ---------------------------------------------------------------------------

def test_descriptor_rejects_a_package_outside_the_tools_namespace():
    with pytest.raises(BuiltinToolPluginError, match="must live under"):
        BuiltinToolPlugin(**{**_VALID_FIELDS, "package": "lingtai.mcp_servers.telegram"})


def test_descriptor_rejects_a_package_that_is_not_its_own_implementation():
    with pytest.raises(BuiltinToolPluginError, match="must be the 'daemon' module"):
        BuiltinToolPlugin(**{**_VALID_FIELDS, "package": "lingtai.tools.avatar"})


def test_descriptor_rejects_a_manual_that_is_not_the_packaged_skill():
    with pytest.raises(BuiltinToolPluginError, match="declares name"):
        BuiltinToolPlugin(**{**_VALID_FIELDS, "manual_skill_name": "somebody-elses-manual"})


def test_descriptor_rejects_a_package_with_no_bundled_manual():
    with pytest.raises(BuiltinToolPluginError, match="cannot read its bundled"):
        BuiltinToolPlugin(
            name="file",
            package="lingtai.tools.file",
            implementation="file",
            summary="s",
            manual_skill_name="file-manual",
        )


@pytest.mark.parametrize("blank_field", sorted(_VALID_FIELDS))
def test_descriptor_rejects_blank_identity_fields(blank_field):
    with pytest.raises(BuiltinToolPluginError, match="non-empty string"):
        BuiltinToolPlugin(**{**_VALID_FIELDS, blank_field: "  "})

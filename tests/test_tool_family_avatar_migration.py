"""Focused declared-host-plugin coverage for Avatar's existing public family."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingtai.kernel.tool_plugin import OFFICIAL_TOOL_PLUGIN_NAMES, ToolPluginHost
from lingtai.tools import avatar
from lingtai.tools.avatar import AvatarManager
from lingtai.tools.avatar._launcher import AvatarLaunchReceipt


class _Workdir:
    def __init__(self, path: Path) -> None:
        self.path = path


class _AvatarParent:
    def __init__(
        self, *, name: str = "parent", venv_path: str | None = None, rules: bool = False
    ) -> None:
        self.parent_name = name
        self.venv_path = venv_path
        self._rules = rules

    def has_rule_privilege(self) -> bool:
        return self._rules


class _Launcher:
    def release(self, _handle) -> None:
        return None


def _host(parent_dir: Path, *, rules: bool = False, venv_path: str | None = None):
    return ToolPluginHost.grant(
        avatar.DECLARATION,
        {
            "workdir": _Workdir(parent_dir),
            "avatar_parent": _AvatarParent(venv_path=venv_path, rules=rules),
        },
    )


def _parent_dir(tmp_path: Path) -> Path:
    parent_dir = tmp_path / "network" / "parent"
    parent_dir.mkdir(parents=True)
    (parent_dir / "init.json").write_text(
        json.dumps({"manifest": {"agent_name": "parent", "language": "en"}}),
        encoding="utf-8",
    )
    return parent_dir


def test_avatar_declaration_is_static_and_matches_its_composed_public_surface():
    declaration = avatar.DECLARATION

    assert declaration.name == "avatar"
    assert declaration.actions == ("spawn", "rules")
    assert declaration.public_actions == ("spawn", "rules", "manual")
    assert declaration.requires == ("workdir", "avatar_parent")
    assert declaration.name in OFFICIAL_TOOL_PLUGIN_NAMES
    assert avatar.get_schema()["properties"]["action"]["enum"] == list(
        declaration.public_actions
    )
    assert dict(avatar._CHILD_SPECS)["manual"] is declaration.manual_input_schema


def test_avatar_manager_uses_only_granted_ports_for_local_manual_and_rules(tmp_path):
    parent_dir = _parent_dir(tmp_path)
    host = _host(parent_dir)
    manager = AvatarManager(host, launcher=_Launcher())

    with pytest.raises(AttributeError, match="did not require host port"):
        host.prompt_section

    before = sorted(path.name for path in parent_dir.iterdir())
    manual = manager({"action": "manual", "input": {}})
    source = Path(avatar.__file__).resolve().parent / "manual" / "SKILL.md"
    assert manual == {
        "status": "ok",
        "action": "manual",
        "manual": source.read_text(encoding="utf-8"),
        "manual_path": str(source),
    }
    assert sorted(path.name for path in parent_dir.iterdir()) == before

    denied = manager({"action": "rules", "input": {"rules_content": "No deleting."}})
    assert denied == {"error": "Not authorized — admin privilege required to set rules"}
    assert not (parent_dir / ".rules").exists()


def test_avatar_spawn_preserves_workdir_identity_venv_and_rules_control(tmp_path, monkeypatch):
    parent_dir = _parent_dir(tmp_path)
    host = _host(parent_dir, rules=True, venv_path="/parent/runtime")
    manager = AvatarManager(host, launcher=_Launcher())
    receipt = AvatarLaunchReceipt(pid=4242, handle=object())
    monkeypatch.setattr(manager, "_launch", lambda working_dir: (receipt, working_dir / "stderr"))
    monkeypatch.setattr(manager, "_wait_for_boot", lambda *_args: ("ok", None))

    dry_run = manager(
        {
            "action": "spawn",
            "input": {"name": "preview", "dry_run": True},
            "_reasoning": "Inspect the regression and summarize the evidence.",
        }
    )
    assert dry_run["status"] == "dry_run"
    assert not (parent_dir.parent / "preview").exists()

    spawned = manager(
        {
            "action": "spawn",
            "input": {"name": "child", "confirm": True},
            "_reasoning": "Inspect the regression and summarize the evidence.",
        }
    )
    child_dir = parent_dir.parent / "child"
    assert spawned["status"] == "ok"
    assert "parent" in (child_dir / ".prompt").read_text(encoding="utf-8")
    assert json.loads((child_dir / "init.json").read_text(encoding="utf-8"))["venv_path"] == "/parent/runtime"

    rules = manager({"action": "rules", "input": {"rules_content": "Be concise."}})
    assert rules["distributed_to"] == ["parent", "child"]
    assert (parent_dir / ".rules").read_text(encoding="utf-8") == "Be concise."
    assert (child_dir / ".rules").read_text(encoding="utf-8") == "Be concise."


def test_agent_mounts_avatar_only_through_the_official_registrar(tmp_path):
    from lingtai.agent import Agent
    from tests._service_helpers import make_gemini_mock_service

    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="avatar-plugin",
        working_dir=tmp_path / "agent",
        capabilities={"avatar": {}},
    )
    try:
        assert agent.official_tool_plugins["avatar"] is avatar.DECLARATION
        assert [schema.name for schema in agent._tool_schemas].count("avatar") == 1
        assert agent.get_capability("avatar") is agent._tool_handlers["avatar"]
        assert isinstance(agent.get_capability("avatar"), AvatarManager)
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ({"action": "spawn"}, "input must be an object"),
        ({"action": "spawn", "input": "not-an-object"}, "input must be an object"),
        (
            {
                "action": "spawn",
                "input": {"name": "child", "confirm": True},
                "dir": "somewhere-else",
            },
            "unsupported avatar argument",
        ),
        (
            {
                "action": "spawn",
                "input": {"name": "child", "rules_content": "No deleting."},
            },
            "unsupported avatar input field",
        ),
    ],
)
def test_avatar_rejects_invalid_input_object_or_root_before_any_io(tmp_path, args, message):
    """The declared family still validates its closed root/input before handlers."""
    parent_dir = _parent_dir(tmp_path)
    manager = AvatarManager(_host(parent_dir), launcher=_Launcher())

    result = manager.handle(args)

    assert result == {
        "status": "failed",
        "error_code": "INVALID_ARGUMENT",
        "message": message,
    }
    assert not (parent_dir.parent / "child").exists()
    assert not (parent_dir / ".rules").exists()
    assert not (parent_dir / "delegates" / "ledger.jsonl").exists()


@pytest.mark.parametrize("summarize", ["yes", 1, None])
def test_avatar_rejects_non_boolean_summarize_before_any_action_io(tmp_path, summarize):
    """The root presentation control is strict and never reaches Avatar actions."""
    parent_dir = _parent_dir(tmp_path)
    manager = AvatarManager(_host(parent_dir), launcher=_Launcher())

    result = manager.handle(
        {
            "action": "spawn",
            "input": {"name": "child", "confirm": True},
            "summarize": summarize,
        }
    )

    assert result == {
        "status": "failed",
        "error_code": "INVALID_ARGUMENT",
        "message": "summarize must be a boolean",
    }
    assert not (parent_dir.parent / "child").exists()
    assert not (parent_dir / "delegates" / "ledger.jsonl").exists()


def test_avatar_clears_normalized_reasoning_between_dispatches(tmp_path):
    """ToolExecutor-normalized reasoning is a one-call mission, never ambient state."""
    parent_dir = _parent_dir(tmp_path)
    manager = AvatarManager(_host(parent_dir), launcher=_Launcher())
    mission = "Investigate the heartbeat regression and report the evidence."

    first = manager.handle(
        {
            "action": "spawn",
            "input": {"name": "first", "dry_run": True},
            "_reasoning": mission,
        }
    )
    second = manager.handle({"action": "spawn", "input": {"name": "second"}})

    assert first["status"] == "dry_run"
    assert first["preview"]["mission"] == mission
    assert second["status"] == "confirmation_needed"
    assert second["preview"]["mission"] == ""
    assert not (parent_dir.parent / "second").exists()


def test_avatar_missing_packaged_manual_degrades_truthfully(tmp_path, monkeypatch):
    """Avatar's declaration promises a package-local manual; no host fallback is hidden."""
    parent_dir = _parent_dir(tmp_path)
    manager = AvatarManager(_host(parent_dir), launcher=_Launcher())

    class _MissingPackageResource:
        def joinpath(self, _path):
            return self

        def read_text(self, *, encoding):
            raise FileNotFoundError("simulated missing package resource")

        def __str__(self):
            return "missing-avatar-package-resource"

    monkeypatch.setattr(avatar.resources, "files", lambda _package: _MissingPackageResource())

    result = manager.handle({"action": "manual", "input": {}})

    assert result == {
        "status": "degraded",
        "action": "manual",
        "manual": "",
        "manual_path": "missing-avatar-package-resource",
        "error": "avatar manual missing",
    }
    assert not (parent_dir / ".rules").exists()
    assert not (parent_dir / "delegates" / "ledger.jsonl").exists()

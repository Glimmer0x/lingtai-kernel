"""Vertical evidence for Shell's declared official host-plugin slice."""
from __future__ import annotations

import sys
import time

import pytest

from lingtai.agent import Agent
from tests._service_helpers import make_gemini_mock_service


@pytest.fixture
def shell_agent(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="shell-tool-plugin-declaration",
        working_dir=tmp_path / "agent",
        capabilities={"shell": {"yolo": True}},
    )
    try:
        yield agent
    finally:
        agent.stop(timeout=1.0)


def _run_input(command: str, *, asynchronous: bool = False) -> dict:
    return {
        "command": command,
        "timeout": None,
        "working_dir": None,
        "async": asynchronous,
        "reminder": None,
    }


def _official_command(marker: str) -> str:
    """Return a command accepted by the selected POSIX/PowerShell dialect."""
    if sys.platform == "win32":
        return f"Write-Output {marker}"
    return f"printf {marker}"


def _official_sleep_command(seconds: int = 30) -> str:
    if sys.platform == "win32":
        return f"Start-Sleep -Seconds {seconds}"
    return f"sleep {seconds}"


def test_shell_declaration_is_static_and_derives_its_shipped_surface():
    from lingtai.kernel.tool_plugin import OFFICIAL_TOOL_PLUGIN_NAMES
    from lingtai.tools.bash._tool_family import DECLARATION, get_schema

    assert DECLARATION.name == "shell"
    assert DECLARATION.actions == ("run", "poll", "cancel")
    assert DECLARATION.public_actions == ("run", "poll", "cancel", "manual")
    assert DECLARATION.requires == ("workdir", "notifications", "configuration")
    assert DECLARATION.manual == "shell"
    assert "shell" in OFFICIAL_TOOL_PLUGIN_NAMES
    assert get_schema()["properties"]["action"]["enum"] == list(DECLARATION.public_actions)


def test_shell_bind_uses_only_its_narrow_ports_and_defers_rehydration(shell_agent, monkeypatch):
    from lingtai.adapters.tool_plugin_host import (
        StaticConfigurationAdapter,
        agent_host_ports,
    )
    from lingtai.kernel.tool_plugin import ToolPluginHost
    from lingtai.tools.bash import ShellManager
    from lingtai.tools.bash._tool_family import DECLARATION

    rehydrated: list[ShellManager] = []
    monkeypatch.setattr(
        ShellManager, "_rehydrate_async_jobs", lambda manager: rehydrated.append(manager)
    )
    host = ToolPluginHost.grant(
        DECLARATION,
        agent_host_ports(
            shell_agent,
            "shell",
            {"configuration": StaticConfigurationAdapter({"yolo": True})},
        ),
    )
    assert host.granted == ("workdir", "notifications", "configuration")
    with pytest.raises(AttributeError, match="prompt_section"):
        host.prompt_section

    bound = DECLARATION.bind(host)
    assert rehydrated == []
    assert bound.activate is not None
    bound.activate()
    assert len(rehydrated) == 1


def test_official_shell_mount_uses_only_narrow_ports_and_keeps_real_dispatch(shell_agent):
    from lingtai.tools.bash._tool_family import DECLARATION

    assert shell_agent.official_tool_plugins["shell"] is DECLARATION
    assert [schema.name for schema in shell_agent._tool_schemas].count("shell") == 1

    handler = shell_agent._tool_handlers["shell"]
    dispatcher = handler.__self__
    manager = dispatcher.manager
    assert manager._agent is None
    assert manager._notifications is not None

    sync = handler({
        "action": "run",
        "input": _run_input(_official_command("official-shell")),
        "reasoning": "verify official Shell execution",
    })
    assert sync["status"] == "ok"
    assert sync["exit_code"] == 0
    assert sync["stdout"] == "official-shell"
    assert sync["command_status"] == "success"

    manual = handler({"action": "manual", "input": {}, "reasoning": "read Shell manual"})
    assert manual["status"] == "ok"
    assert manual["content"][0]["text"]
    assert manual["structuredContent"]["manual_path"].endswith(
        "capabilities/shell/SKILL.md"
    )


def test_official_shell_async_run_and_poll_keep_durable_engine_semantics(shell_agent):
    handler = shell_agent._tool_handlers["shell"]
    started = handler({
        "action": "run",
        "input": _run_input(_official_command("official-async"), asynchronous=True),
        "reasoning": "verify official Shell async supervision",
    })
    assert started["status"] == "ok"
    job_id = started["job_id"]

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = handler({
            "action": "poll",
            "input": {"job_id": job_id},
            "reasoning": "read durable async result",
        })
        if result["status"] == "done":
            break
        time.sleep(0.05)
    else:  # pragma: no cover - assertion branch is the evidence
        pytest.fail("official Shell async job did not reach a durable terminal result")

    assert result["exit_code"] == 0
    assert result["stdout"] == "official-async"
    assert result["command_status"] == "success"


def test_official_shell_async_cancel_is_native_route_safe(shell_agent):
    handler = shell_agent._tool_handlers["shell"]
    started = handler({
        "action": "run",
        "input": _run_input(_official_sleep_command(), asynchronous=True),
        "reasoning": "verify official Shell cancellation",
    })
    assert started["status"] == "ok"
    cancelled = handler({
        "action": "cancel",
        "input": {"job_id": started["job_id"]},
        "reasoning": "cancel official Shell async job",
    })
    assert cancelled == {"status": "cancelled", "job_id": started["job_id"]}

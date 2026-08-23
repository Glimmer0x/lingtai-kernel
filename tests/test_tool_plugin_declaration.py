"""Focused vertical proofs for declared official host-plugin mounts.

The shared kernel contract is exercised by the live MCP and notification
slices: each declaration is claimed and mounted only through the registrar,
and the tool retains its public dispatch behavior.  Broader declaration
validation remains owned by the kernel contract suite.
"""
from __future__ import annotations

import json

import pytest

from lingtai.agent import Agent
from tests._service_helpers import make_gemini_mock_service


@pytest.fixture
def mcp_agent(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="tool-plugin-declaration",
        working_dir=tmp_path / "agent",
        capabilities={"mcp": {}},
        addons=["imap"],
    )
    try:
        yield agent
    finally:
        agent.stop(timeout=1.0)


def test_official_mcp_mount_uses_controlled_host_and_real_dispatch(mcp_agent):
    """Boot registration claims the declaration and dispatches both actions."""
    from lingtai.tools.mcp import DECLARATION

    assert DECLARATION.requires == ("workdir", "prompt_section")
    assert mcp_agent.official_tool_plugins["mcp"] is DECLARATION
    assert [schema.name for schema in mcp_agent._tool_schemas].count("mcp") == 1

    handler = mcp_agent._tool_handlers["mcp"]
    info = handler({"action": "info", "input": {}, "reasoning": "health"})
    assert info["status"] == "ok"
    assert info["registered"][0]["name"] == "imap"
    assert "mcp_manual" not in info

    manual = handler({"action": "manual", "input": {}, "reasoning": "guidance"})
    assert manual["status"] == "ok"
    assert manual["mcp_manual"]
    assert manual["manual_path"].endswith("capabilities/mcp/SKILL.md")


def test_official_notification_mount_preserves_core_state_and_packaged_manual(mcp_agent):
    """The notification declaration reaches real Core state only through its port."""
    from lingtai.kernel.notifications import submit
    from lingtai.tools.notification import DECLARATION

    assert DECLARATION.requires == ("workdir", "notification_state")
    assert mcp_agent.official_tool_plugins["notification"] is DECLARATION
    assert [schema.name for schema in mcp_agent._tool_schemas].count("notification") == 1

    handler = mcp_agent._tool_handlers["notification"]
    check = handler({"action": "check", "input": {}, "reasoning": "probe"})
    assert check["_notification_placeholder"] is True

    manual = handler({"action": "manual", "input": {}, "reasoning": "guidance"})
    assert manual["status"] == "ok"
    assert manual["notification_manual"]
    assert manual["manual_path"].endswith("capabilities/notification/SKILL.md")

    submit(mcp_agent, "system", data={"events": []}, header="dismiss me")
    dismissed = handler(
        {
            "action": "dismiss_channel",
            "input": {"channel": "system", "force": True, "reason": None},
            "reasoning": "clear the mirror only",
        }
    )
    assert dismissed == {
        "status": "ok",
        "channel": "system",
        "cleared": True,
        "forced": True,
    }
    assert not (mcp_agent.working_dir / ".notification" / "system.json").exists()


@pytest.mark.parametrize(
    "construction_kwargs",
    [
        pytest.param({"capabilities": {"notification": None}}, id="capabilities-null"),
        pytest.param({"capabilities": {}, "disable": ["notification"]}, id="disable-list"),
    ],
)
def test_notification_is_mounted_once_on_live_construction_despite_opt_out(
    tmp_path, construction_kwargs
):
    """Both capability-shaped opt-outs preserve one live official Notification mount."""
    from lingtai.agent import Agent

    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="notification-always-on-construction",
        working_dir=tmp_path / "agent",
        **construction_kwargs,
    )
    try:
        from lingtai.tools.notification import DECLARATION

        assert agent.official_tool_plugins["notification"] is DECLARATION
        assert [schema.name for schema in agent._tool_schemas].count("notification") == 1
        assert list(name for name in agent._tool_handlers if name == "notification") == [
            "notification"
        ]
        assert agent._tool_handlers["notification"](
            {"action": "check", "input": {}, "reasoning": "live construction"}
        )["_notification_placeholder"] is True
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize(
    "manifest_overrides",
    [
        pytest.param({"capabilities": {"notification": None}}, id="refresh-capabilities-null"),
        pytest.param({"capabilities": {}, "disable": ["notification"]}, id="refresh-disable-list"),
    ],
)
def test_notification_is_remounted_once_on_live_refresh_despite_opt_out(
    tmp_path, manifest_overrides
):
    """Refresh clears/rebuilds the surface but cannot remove the official mount."""
    from lingtai.agent import Agent

    workdir = tmp_path / "agent"
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="notification-always-on-refresh",
        working_dir=workdir,
        capabilities={},
    )
    try:
        manifest = {
            "agent_name": "notification-always-on-refresh",
            "language": "en",
            "llm": {
                "provider": "gemini",
                "model": "gemini-test",
                "api_key": "test-key",
                "base_url": None,
            },
            "capabilities": {},
            "soul": {"delay": 60},
            "stamina": 3600,
            "context_limit": None,
            "molt_pressure": 0.8,
            "molt_prompt": "",
            "max_turns": 100,
            "admin": {"karma": True},
            "streaming": False,
            **manifest_overrides,
        }
        (workdir / "init.json").write_text(
            json.dumps({
                "manifest": manifest,
                "principle": "",
                "covenant": "",
                "pad": "",
                "lingtai": "",
            }),
            encoding="utf-8",
        )

        agent._setup_from_init()

        from lingtai.tools.notification import DECLARATION

        assert agent.official_tool_plugins["notification"] is DECLARATION
        assert [schema.name for schema in agent._tool_schemas].count("notification") == 1
        assert list(name for name in agent._tool_handlers if name == "notification") == [
            "notification"
        ]
        assert agent._tool_handlers["notification"](
            {"action": "check", "input": {}, "reasoning": "live refresh"}
        )["_notification_placeholder"] is True
    finally:
        agent.stop(timeout=1.0)

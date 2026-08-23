"""Compact direct coverage for official declared host-plugin mounts.

Each vertical slice proves the registrar claims its static declaration and the
real ``info``/``manual`` dispatch remains usable.  MCP remains covered here;
Plugin additionally proves its read-only catalog projection reaches the existing
registration/discovery semantics without accepting a whole Agent.
"""
from __future__ import annotations

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


@pytest.fixture
def plugin_agent(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="tool-plugin-declaration",
        working_dir=tmp_path / "agent",
        capabilities={"plugin": {}},
    )
    try:
        yield agent
    finally:
        agent.stop(timeout=1.0)


def test_official_plugin_mount_uses_only_catalog_state_and_real_dispatch(plugin_agent):
    """Plugin's declaration mounts through the controlled host path unchanged."""
    from lingtai.kernel.tool_plugin import OFFICIAL_TOOL_PLUGIN_NAMES
    from lingtai.tools.plugin import DECLARATION

    assert OFFICIAL_TOOL_PLUGIN_NAMES == ("mcp", "plugin")
    assert DECLARATION.requires == ("workdir", "prompt_section", "plugin_catalog")
    assert plugin_agent.official_tool_plugins["plugin"] is DECLARATION
    assert [schema.name for schema in plugin_agent._tool_schemas].count("plugin") == 1

    handler = plugin_agent._tool_handlers["plugin"]
    info = handler({"action": "info", "input": {}, "reasoning": "health"})
    assert info["status"] == "ok"
    assert info["registered"] == []
    assert info["discovered"] == []
    assert "plugin_manual" not in info

    manual = handler({"action": "manual", "input": {}, "reasoning": "guidance"})
    assert manual["status"] == "ok"
    assert manual["plugin_manual"]
    assert manual["manual_path"].endswith("capabilities/plugin/SKILL.md")

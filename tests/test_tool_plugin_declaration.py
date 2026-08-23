"""Focused behavioral coverage for official declared-host-plugin mounts.

MCP and Vision each prove their static declaration reaches the controlled host
registrar and still dispatches its real public actions. Name-reservation and
forged/external mount rejection remain covered by the shared kernel suite.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from lingtai.agent import Agent
from lingtai.services.vision import VisionService
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


def test_official_vision_mount_keeps_active_provider_and_packaged_manual(tmp_path):
    """Vision binds only declared ports and remains a real public tool."""
    from lingtai.tools.vision import DECLARATION

    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="vision-tool-plugin-declaration",
        working_dir=tmp_path / "agent",
        capabilities={"vision": {"vision_service": MagicMock(spec=VisionService)}},
    )
    try:
        assert DECLARATION.requires == ("workdir", "active_provider", "configuration")
        assert agent.official_tool_plugins["vision"] is DECLARATION
        assert [schema.name for schema in agent._tool_schemas].count("vision") == 1

        handler = agent._tool_handlers["vision"]
        manual = handler({"action": "manual", "input": {}, "reasoning": "guidance"})
        assert manual["status"] == "ok"
        assert manual["action"] == "manual"
        assert manual["manual"]
        assert manual["manual_path"].endswith("capabilities/vision/SKILL.md")
    finally:
        agent.stop(timeout=1.0)

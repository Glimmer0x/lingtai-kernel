"""Focused behavioral coverage for the official ``mcp`` host-plugin mount.

The shared primitive needs one vertical proof here: the official declaration is
mounted through the registrar's controlled host path and its real ``info`` and
``manual`` dispatch remain usable. Reservation and failed external mounts are
covered by the focused MCP connection tests in ``test_mcp_capability.py``.
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

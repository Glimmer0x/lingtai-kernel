"""Focused live proofs for the official MCP and Soul host-plugin mounts."""
from __future__ import annotations

import pytest

from lingtai.agent import Agent
from tests._service_helpers import make_gemini_mock_service


@pytest.fixture
def declared_agent(tmp_path):
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


def test_official_mcp_mount_uses_controlled_host_and_real_dispatch(declared_agent):
    """MCP remains the signpost slice on its two earned ports."""
    from lingtai.tools.mcp import DECLARATION

    assert DECLARATION.requires == ("workdir", "prompt_section")
    assert declared_agent.official_tool_plugins["mcp"] is DECLARATION
    assert [schema.name for schema in declared_agent._tool_schemas].count("mcp") == 1

    handler = declared_agent._tool_handlers["mcp"]
    info = handler({"action": "info", "input": {}, "reasoning": "health"})
    assert info["status"] == "ok"
    assert info["registered"][0]["name"] == "imap"
    assert "mcp_manual" not in info

    manual = handler({"action": "manual", "input": {}, "reasoning": "guidance"})
    assert manual["status"] == "ok"
    assert manual["mcp_manual"]
    assert manual["manual_path"].endswith("capabilities/mcp/SKILL.md")


def test_official_soul_mount_preserves_real_flow_and_packaged_manual(declared_agent):
    """Soul uses its earned self/runtime port, without a second public root."""
    from lingtai.kernel.tool_plugin import OFFICIAL_TOOL_PLUGIN_NAMES
    from lingtai.tools.soul import DECLARATION

    assert OFFICIAL_TOOL_PLUGIN_NAMES == ("mcp", "soul")
    assert DECLARATION.public_actions == (
        "inquiry", "flow", "config", "voice", "dismiss", "manual",
    )
    assert DECLARATION.requires == ("workdir", "soul_runtime")
    assert declared_agent.official_tool_plugins["soul"] is DECLARATION
    assert [schema.name for schema in declared_agent._tool_schemas].count("soul") == 1

    handler = declared_agent._tool_handlers["soul"]
    disabled = handler({"action": "flow", "input": {}, "reasoning": "health"})
    assert disabled["status"] == "disabled"
    assert disabled["enabled"] is False

    manual = handler({"action": "manual", "input": {}, "reasoning": "guidance"})
    assert manual["status"] == "ok"
    assert manual["manual"]
    assert manual["manual_path"].endswith("capabilities/soul-manual/SKILL.md")

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


@pytest.fixture
def task_card_agent(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="task-card-plugin-declaration",
        working_dir=tmp_path / "agent",
        capabilities={"task_card": {}},
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


def test_official_task_card_mount_keeps_the_current_agent_lifecycle(task_card_agent):
    """The second declared slice mounts, retains its manager, and serves its package manual."""
    from lingtai.tools.task_card import DECLARATION, TaskCardManager

    assert DECLARATION.requires == (
        "workdir", "shutdown", "task_card_lifecycle", "task_card_notifications"
    )
    assert task_card_agent.official_tool_plugins["task_card"] is DECLARATION
    assert [schema.name for schema in task_card_agent._tool_schemas].count("task_card") == 1

    manager = task_card_agent._task_card_manager
    assert isinstance(manager, TaskCardManager)
    handler = task_card_agent._tool_handlers["task_card"]
    assert handler.__self__ is manager
    manual = handler({"action": "manual", "input": {}, "reasoning": "guidance"})
    assert manual["status"] == "ok"
    assert manual["content"][0]["text"]
    assert manual["structuredContent"]["manual_path"].endswith(
        "capabilities/task_card/SKILL.md"
    )

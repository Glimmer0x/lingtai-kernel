"""Focused behavioral coverage for official declared host-plugin mounts.

The shared primitive has three real vertical proofs: ``mcp`` demonstrates the
small presentation-only slice, ``daemon`` demonstrates a manager-owning slice
that consumes its current-agent model/tool/preset/notification semantics through
the capability-native runtime port, and ``plugin`` demonstrates a slice whose
only earned port is a detached read-only projection.  All three are mounted only
through the registrar's controlled host path.
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
def daemon_agent(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="daemon-plugin-declaration",
        working_dir=tmp_path / "agent",
        capabilities={"daemon": {}},
    )
    try:
        yield agent
    finally:
        agent.stop(timeout=1.0)


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


def test_all_seven_official_families_mount_exactly_once_together(tmp_path):
    """The cumulative composition keeps every landed family and no duplicate."""
    from lingtai.kernel.tool_plugin import OFFICIAL_TOOL_PLUGIN_NAMES

    assert OFFICIAL_TOOL_PLUGIN_NAMES == (
        "mcp", "avatar", "context", "daemon", "email", "file", "plugin"
    )
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="all-seven-official-plugins",
        working_dir=tmp_path / "agent",
        capabilities={
            "mcp": {},
            "avatar": {},
            "context": {},
            "daemon": {},
            "file": {},
            "plugin": {},
        },
    )
    try:
        assert set(agent.official_tool_plugins) == set(OFFICIAL_TOOL_PLUGIN_NAMES)
        mounted_names = [schema.name for schema in agent._tool_schemas]
        for name in OFFICIAL_TOOL_PLUGIN_NAMES:
            assert mounted_names.count(name) == 1, name
            assert name in agent._tool_handlers
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


def test_official_daemon_mount_uses_runtime_port_and_preserves_dispatch(daemon_agent):
    """Daemon keeps one real manager/tool surface without binding to an Agent.

    ``list`` exercises the unchanged manager's durable-state path (no process is
    spawned), and ``manual`` proves that the declaration's installed manual is
    the registered reserved child rather than the legacy flat manager branch.
    """
    from lingtai.tools.daemon import DECLARATION, DaemonManager

    assert DECLARATION.requires == ("workdir", "daemon_runtime")
    assert daemon_agent.official_tool_plugins["daemon"] is DECLARATION
    assert [schema.name for schema in daemon_agent._tool_schemas].count("daemon") == 1

    manager = daemon_agent._capability_managers["daemon"]
    assert isinstance(manager, DaemonManager)
    assert not hasattr(manager, "_agent")
    assert manager._runtime.service is daemon_agent.service

    handler = daemon_agent._tool_handlers["daemon"]
    listed = handler(
        {
            "action": "list",
            "input": {
                "contains": None,
                "status": None,
                "include_done": None,
                "last": None,
            },
            "reasoning": "inspect daemon state",
        }
    )
    assert listed["emanations"] == []
    assert listed["history_included"] is True

    manual = handler({"action": "manual", "input": {}, "reasoning": "guidance"})
    assert manual["status"] == "ok"
    assert manual["structuredContent"]["manual_path"].endswith(
        "capabilities/daemon/SKILL.md"
    )
    assert manual["content"][0]["text"]


def test_official_daemon_manager_reads_replaced_notification_route_for_retryable_terminal_state(
    daemon_agent, monkeypatch,
):
    """The official Daemon binding must not retain a stale notification callback.

    A terminal publish runs through the manager produced by the declared-host
    registration. Replacing its host notification route after binding with a
    failure must make publication fail; once the durable claim is cleared by the
    terminal caller, the run can claim the same terminal notification again.
    """
    from lingtai.tools.daemon import DaemonManager
    from lingtai.tools.daemon.run_dir import DaemonRunDir

    manager = daemon_agent._capability_managers["daemon"]
    assert isinstance(manager, DaemonManager)
    assert daemon_agent.official_tool_plugins["daemon"].name == "daemon"

    run_dir = DaemonRunDir(
        parent_working_dir=daemon_agent.working_dir,
        handle="em-live-route",
        run_id="em-live-route",
        task="exercise live daemon notification route",
        tools=[],
        model="test-model",
        max_turns=1,
        timeout_s=1.0,
        parent_addr="daemon-plugin-declaration",
        parent_pid=0,
        system_prompt="",
    )
    run_dir.mark_done("terminal result")
    idempotency_key = run_dir.claim_terminal_notification("done")
    assert idempotency_key is not None

    def replaced_route(**_kwargs):
        raise OSError("replacement notification route failed")

    monkeypatch.setattr(daemon_agent, "_enqueue_system_notification", replaced_route)
    assert manager._publish_daemon_notification(
        "em-live-route",
        status="done",
        text="terminal result",
        run_dir=run_dir,
        idempotency_key=idempotency_key,
    ) is False

    run_dir.clear_terminal_notification_claim()
    state = run_dir.state_snapshot()
    assert state["terminal_notified"] is False
    assert state["terminal_notification_claim"] is None
    assert run_dir.claim_terminal_notification("done") == idempotency_key


def test_official_plugin_mount_uses_only_catalog_state_and_real_dispatch(plugin_agent):
    """Plugin's declaration mounts through the controlled host path unchanged."""
    from lingtai.tools.plugin import DECLARATION

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


def test_standard_port_table_grants_each_declaration_only_its_requires(plugin_agent):
    """A standard-table port is reachable only by a declaration that names it.

    ``plugin_catalog`` and ``avatar_parent`` are built for every declaration in
    ``agent_host_ports``. This proves that placement in the full table is not a
    grant: MCP, which requires neither, cannot reach either one through its
    least-privilege facade, while Plugin reaches exactly its three.
    """
    from lingtai.adapters.tool_plugin_host import (
        AgentPluginCatalogAdapter,
        agent_host_ports,
    )
    from lingtai.kernel.tool_plugin import PluginCatalogState, ToolPluginHost
    from lingtai.tools.mcp import DECLARATION as MCP_DECLARATION
    from lingtai.tools.plugin import DECLARATION as PLUGIN_DECLARATION

    table = agent_host_ports(plugin_agent, "plugin")
    assert isinstance(table["plugin_catalog"], AgentPluginCatalogAdapter)

    plugin_host = ToolPluginHost.grant(PLUGIN_DECLARATION, table)
    assert plugin_host.granted == ("workdir", "prompt_section", "plugin_catalog")
    assert isinstance(plugin_host.plugin_catalog.read_state(), PluginCatalogState)

    mcp_host = ToolPluginHost.grant(
        MCP_DECLARATION, agent_host_ports(plugin_agent, "mcp")
    )
    assert mcp_host.granted == ("workdir", "prompt_section")
    with pytest.raises(AttributeError):
        mcp_host.plugin_catalog
    with pytest.raises(AttributeError):
        mcp_host.avatar_parent

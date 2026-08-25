"""Atomic ownership tests for the process-local stdio MCP overlay."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import lingtai.services.session_mcp as session_mcp
from lingtai.kernel.llm import FunctionSchema
from lingtai.services.session_mcp import StdioMCPServerConfig


class _Agent:
    def __init__(self):
        self._intrinsics = {}
        self._tool_handlers = {"existing": lambda args: args}
        self._tool_schemas = []
        self._mcp_tool_names = set()
        self._mcp_clients_by_tool = {}
        self._mcp_tool_metadata = {}
        self._chat = None
        self._token_decomp_dirty = False

    def _build_tool_schemas(self):
        return self._tool_schemas


class _Client:
    plans = []
    made = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.plan = self.plans.pop(0)
        self.closed = False
        self.made.append(self)

    def start(self):
        if isinstance(self.plan, Exception):
            raise self.plan

    def list_tools(self):
        return self.plan

    def call_tool(self, name, args):
        return {"name": name, "args": args}

    def close(self):
        self.closed = True


def _config(name="one"):
    return StdioMCPServerConfig(name, "/bin/server", ("--stdio",), (("A", "B"),))


@pytest.fixture(autouse=True)
def _fake_client(monkeypatch):
    _Client.plans = []
    _Client.made = []
    monkeypatch.setattr(session_mcp, "MCPClient", _Client)


def test_session_mcp_publishes_all_tools_and_close_removes_only_owned():
    agent = _Agent()
    _Client.plans = [[{"name": "demo", "schema": {"type": "object"}, "description": "D"}]]
    lease = session_mcp.mount_session_mcp_stdio(agent, (_config(),))
    assert set(agent._tool_handlers) == {"existing", "demo"}
    assert agent._tool_handlers["demo"]({"x": 1})["name"] == "demo"
    assert _Client.made[0].kwargs["env"] == {"A": "B"}
    lease.close()
    lease.close()
    assert set(agent._tool_handlers) == {"existing"}
    assert _Client.made[0].closed


@pytest.mark.parametrize("plans", [
    [[{"name": "same", "schema": {}}, {"name": "same", "schema": {}}]],
    [[{"name": "existing", "schema": {}}]],
    [[{"name": "file", "schema": {}}]],
])
def test_session_mcp_rejects_duplicate_and_existing_tool_collisions(plans):
    agent = _Agent()
    _Client.plans = plans
    with pytest.raises(ValueError):
        session_mcp.mount_session_mcp_stdio(agent, (_config(),))
    assert set(agent._tool_handlers) == {"existing"}
    assert all(client.closed for client in _Client.made)


def test_session_mcp_partial_start_rolls_back_every_client_and_tool():
    agent = _Agent()
    _Client.plans = [[{"name": "first", "schema": {}}], RuntimeError("boom")]
    with pytest.raises(RuntimeError, match="boom"):
        session_mcp.mount_session_mcp_stdio(agent, (_config("one"), _config("two")))
    assert set(agent._tool_handlers) == {"existing"}
    assert len(_Client.made) == 2
    assert all(client.closed for client in _Client.made)


def test_session_mcp_close_still_closes_child_when_live_tool_refresh_fails():
    agent = _Agent()
    _Client.plans = [[{"name": "demo", "schema": {}}]]
    lease = session_mcp.mount_session_mcp_stdio(agent, (_config(),))
    agent._chat = SimpleNamespace(update_tools=lambda tools: (_ for _ in ()).throw(RuntimeError("refresh")))
    lease.close()
    assert _Client.made[0].closed
    assert "demo" not in agent._tool_handlers

def test_session_mcp_mount_refresh_failure_rolls_back_lease_and_children():
    agent = _Agent()
    agent._chat = SimpleNamespace(
        update_tools=lambda tools: (_ for _ in ()).throw(RuntimeError("refresh"))
    )
    _Client.plans = [[{"name": "demo", "schema": {}}]]
    with pytest.raises(RuntimeError, match="refresh"):
        session_mcp.mount_session_mcp_stdio(agent, (_config(),))
    assert "demo" not in agent._tool_handlers
    assert getattr(agent, "_session_mcp_leases", []) == []
    assert _Client.made[0].closed


def test_session_mcp_close_removes_owned_route_but_keeps_later_handler_owner():
    agent = _Agent()
    _Client.plans = [[{"name": "demo", "schema": {}}]]
    lease = session_mcp.mount_session_mcp_stdio(agent, (_config(),))

    replacement_handler = lambda args: {"replacement": args}
    replacement_schema = FunctionSchema(
        name="demo", description="replacement", parameters={"type": "object"}
    )
    agent._tool_handlers["demo"] = replacement_handler
    agent._tool_schemas = [replacement_schema]

    lease.close()
    assert agent._tool_handlers["demo"] is replacement_handler
    assert "demo" not in agent._mcp_clients_by_tool
    assert "demo" not in agent._mcp_tool_metadata
    assert "demo" not in agent._mcp_tool_names
    assert agent._tool_schemas == [replacement_schema]
    assert _Client.made[0].closed

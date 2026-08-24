"""Focused vertical proof for the official System declared-host plugin."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingtai.agent import Agent
from lingtai.adapters.tool_plugin_host import agent_host_ports
from lingtai.kernel.state import AgentState
from lingtai.kernel.tool_plugin import ToolPluginHost
from lingtai.tools.system import DECLARATION, get_schema
from tests._service_helpers import make_gemini_mock_service


def test_system_declaration_is_static_and_the_real_agent_mounts_it_once(tmp_path):
    """System keeps its surface while lifecycle/identity enter only through ports."""
    assert DECLARATION.name == "system"
    assert DECLARATION.public_actions == (
        "refresh", "sleep", "lull", "interrupt", "suspend", "cpr", "clear",
        "nirvana", "presets", "name_set", "name_nickname", "manual",
    )
    assert DECLARATION.requires == ("workdir", "system_runtime", "identity")
    assert get_schema()["properties"]["action"]["enum"] == list(DECLARATION.public_actions)

    agent = Agent(
        service=make_gemini_mock_service(),
        working_dir=tmp_path / "agent",
        capabilities={},
    )
    try:
        assert agent.official_tool_plugins["system"] is DECLARATION
        assert [schema.name for schema in agent._tool_schemas].count("system") == 1
        assert [schema.name for schema in agent._build_tool_schemas()].count("system") == 1

        host = ToolPluginHost.grant(DECLARATION, agent_host_ports(agent, "system"))
        assert host.granted == DECLARATION.requires
        assert not hasattr(host, "agent")

        handler = agent._tool_handlers["system"]
        named = handler({"action": "name_set", "input": {"content": "Port Name"}, "reasoning": "identity"})
        assert named == {"status": "ok", "name": "Port Name"}
        manual = handler({"action": "manual", "input": {}, "reasoning": "guidance"})
        assert manual["status"] == "ok"
        assert manual["manual"]
        assert manual["manual_path"].endswith("capabilities/system-manual/SKILL.md")

        slept = handler({
            "action": "sleep",
            "input": {"reason": "runtime bridge"},
            "reasoning": "lifecycle",
        })
        assert slept["status"] == "ok"
        assert agent.state is AgentState.ASLEEP
        assert agent._asleep.is_set()
    finally:
        agent.stop(timeout=1.0)


@pytest.mark.parametrize("route", ("direct", "mounted"))
@pytest.mark.parametrize("force,should_sleep", ((False, False), (True, True)))
def test_system_sleep_direct_and_mounted_routes_have_refusal_force_parity(
    tmp_path, route: str, force: bool, should_sleep: bool
):
    """Both public entry points exercise the same pending-attention contract.

    The notification and agent directories are disposable.  ``force`` is the
    only variation: ordinary sleep must refuse a new payload, while the
    explicit escape hatch may transition to ASLEEP.
    """
    agent = Agent(
        service=make_gemini_mock_service(),
        working_dir=tmp_path / route,
        capabilities={},
    )
    try:
        notification_dir = agent.working_dir / ".notification"
        notification_dir.mkdir(parents=True, exist_ok=True)
        (notification_dir / "email.json").write_text(
            json.dumps({"header": "pending", "priority": "normal", "data": {}}),
            encoding="utf-8",
        )
        # The payload is intentionally newer than the last committed snapshot.
        agent._notification_fp = ()
        envelope = {
            "action": "sleep",
            "input": {"reason": "parity", "force": force},
            "reasoning": "bounded parity test",
        }
        if route == "mounted":
            result = agent._tool_handlers["system"](envelope)
        else:
            from lingtai.tools.system import handle

            result = handle(agent, envelope)

        assert result["status"] == "ok"
        assert (agent.state is AgentState.ASLEEP) is should_sleep
        assert agent._asleep.is_set() is should_sleep
        if not should_sleep:
            assert "refused" in result["message"].lower()
    finally:
        agent.stop(timeout=1.0)


def test_system_manual_contains_declared_ltp_profile_and_no_settings_statement():
    """The canonical source manual teaches the obligations its schema advertises."""
    manual_path = (
        Path(__file__).parents[1]
        / "src"
        / "lingtai"
        / "intrinsic_skills"
        / "system-manual"
        / "SKILL.md"
    )
    body = manual_path.read_text(encoding="utf-8")
    assert DECLARATION.manual == "system-manual"
    assert '"action": "<one action from the installed schema>"' in body
    assert '"input": {"<fields for that action only>": "..."}' in body
    assert "presets` can return a large allowed-only catalog" in body
    assert "action itself must always use `summarize=false`" in body
    assert "no `settings/system.json` and no per-action settings file" in body

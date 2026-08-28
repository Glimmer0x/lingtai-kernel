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
from lingtai.tools.system import settings as system_settings
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

        original_request_cancel = agent._request_turn_cancel
        cancel_observations = []

        def request_cancel():
            cancel_observations.append((agent.state, agent._asleep.is_set()))
            original_request_cancel()

        agent._request_turn_cancel = request_cancel
        slept = handler({
            "action": "sleep",
            "input": {"reason": "runtime bridge"},
            "reasoning": "lifecycle",
        })
        assert slept["status"] == "ok"
        assert cancel_observations == [(AgentState.ASLEEP, True)]
        assert agent.state is AgentState.ASLEEP
        assert agent._asleep.is_set()
        assert agent._cancel_event.is_set()
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


def test_system_is_remounted_once_on_live_refresh(tmp_path):
    """Refresh clears and rebuilds the official surface with one System mount."""
    workdir = tmp_path / "agent"
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="system-refresh-remount",
        working_dir=workdir,
        capabilities={},
    )
    try:
        manifest = {
            "agent_name": "system-refresh-remount",
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
            "admin": {},
            "streaming": False,
        }
        (workdir / "init.json").write_text(
            json.dumps(
                {
                    "manifest": manifest,
                    "principle": "",
                    "covenant": "",
                    "pad": "",
                    "lingtai": "",
                }
            ),
            encoding="utf-8",
        )

        agent._setup_from_init()

        assert agent.official_tool_plugins["system"] is DECLARATION
        assert [schema.name for schema in agent._tool_schemas].count("system") == 1
        presets = agent._tool_handlers["system"](
            {"action": "presets", "input": {}, "reasoning": "live refresh"}
        )
        assert presets["status"] == "ok"
    finally:
        agent.stop(timeout=1.0)


def _settings_agent(workdir: Path):
    return type("SettingsAgent", (), {"_working_dir": workdir})()


def _write_budget(workdir: Path, value: object = 250_000) -> Path:
    path = workdir / "settings" / "system.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "cache_miss_budget": value}),
        encoding="utf-8",
    )
    return path


def test_system_budget_uses_env_then_file_then_default(monkeypatch, tmp_path):
    agent = _settings_agent(tmp_path)
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000

    _write_budget(tmp_path)
    assert system_settings.resolve_cache_miss_budget(agent) == 250_000

    monkeypatch.setenv(system_settings.CACHE_MISS_BUDGET_ENV, "bad")
    assert system_settings.resolve_cache_miss_budget(agent) == 250_000

    monkeypatch.setattr(
        Path,
        "read_text",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("a valid env value must bypass System JSON")
        ),
    )
    monkeypatch.setenv(system_settings.CACHE_MISS_BUDGET_ENV, "3000000")
    assert system_settings.resolve_cache_miss_budget(agent) == 3_000_000


@pytest.mark.parametrize(
    "body",
    (
        "{",
        "[]",
        # A v2 document is now a valid System document (see
        # tests/test_system_runtime_policy.py); only unknown versions reject.
        '{"schema_version": 3, "cache_miss_budget": 1}',
        '{"schema_version": 2, "cache_miss_budget": 1, "extra": 2}',
        '{"schema_version": 1, "cache_miss_budget": 0}',
        '{"schema_version": 1, "cache_miss_budget": true}',
        '{"schema_version": 1, "cache_miss_budget": "123"}',
        '{"schema_version": 1, "cache_miss_budget": 1.5}',
        '{"schema_version": 1, "cache_miss_budget": 1, "extra": 2}',
        '{"schema_version": 1, "cache_miss_budget": 1, "cache_miss_budget": 2}',
    ),
)
def test_system_budget_invalid_documents_use_default(monkeypatch, tmp_path, body):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    path = tmp_path / "settings" / "system.json"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    assert system_settings.resolve_cache_miss_budget(_settings_agent(tmp_path)) == 2_000_000


def test_outer_agent_budget_hook_delegates_to_system(monkeypatch, tmp_path):
    subject = _settings_agent(tmp_path)
    monkeypatch.setattr(system_settings, "resolve_cache_miss_budget", lambda agent: 123)
    assert Agent.resolve_cache_miss_budget(subject) == 123


def test_system_manual_contains_declared_ltp_and_budget_settings_contract():
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
    for required in (
        "<agent-workdir>/settings/system.json",
        '"schema_version": 1',
        '"cache_miss_budget": 2000000',
        "LINGTAI_CACHE_MISS_BUDGET",
        "2,000,000",
        ".notification/system.json",
        "manifest.cache_miss_budget",
    ):
        assert required in body

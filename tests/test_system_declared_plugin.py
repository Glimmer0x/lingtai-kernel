"""Focused vertical proof for the official System declared-host plugin."""
from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

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
    events = []
    agent = SimpleNamespace(
        _working_dir=workdir,
        _log=lambda event, **fields: events.append((event, fields)),
    )
    return agent, events


def _write_budget_settings(workdir: Path, budget: int) -> Path:
    path = workdir / "settings" / "system.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": 1, "cache_miss_budget": budget}),
        encoding="utf-8",
    )
    return path


def test_outer_agent_cache_miss_budget_hook_lazily_delegates_to_system(monkeypatch):
    seen = []

    def delegated(agent):
        seen.append(agent)
        return 345_678

    monkeypatch.setattr(system_settings, "resolve_cache_miss_budget", delegated)
    subject = SimpleNamespace()

    assert Agent.resolve_cache_miss_budget(subject) == 345_678
    assert seen == [subject]


def test_system_settings_resolve_valid_file_and_missing_default(monkeypatch, tmp_path):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    agent, events = _settings_agent(tmp_path)

    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000
    assert events == []

    _write_budget_settings(tmp_path, 250_000)
    assert system_settings.resolve_cache_miss_budget(agent) == 250_000
    assert events == []


@pytest.mark.parametrize(
    "raw, reason",
    [
        (b"{", "malformed_json"),
        (b"\xff", "invalid_utf8"),
        (b"[]", "not_object"),
        (b"{}", "invalid_schema"),
        (b'{"schema_version":1}', "invalid_schema"),
        (b'{"cache_miss_budget":1}', "invalid_schema"),
        (
            b'{"schema_version":1,"cache_miss_budget":1,"unknown":2}',
            "invalid_schema",
        ),
        (
            b'{"schema_version":1,"schema_version":1,"cache_miss_budget":1}',
            "duplicate_key",
        ),
        (
            b'{"schema_version":1,"cache_miss_budget":1,"cache_miss_budget":2}',
            "duplicate_key",
        ),
        (
            b'{"schema_version":true,"cache_miss_budget":1}',
            "invalid_schema_version",
        ),
        (
            b'{"schema_version":"1","cache_miss_budget":1}',
            "invalid_schema_version",
        ),
        (
            b'{"schema_version":1.0,"cache_miss_budget":1}',
            "invalid_schema_version",
        ),
        (
            b'{"schema_version":2,"cache_miss_budget":1}',
            "unsupported_schema_version",
        ),
        (b'{"schema_version":1,"cache_miss_budget":true}', "invalid_value"),
        (b'{"schema_version":1,"cache_miss_budget":0}', "invalid_value"),
        (b'{"schema_version":1,"cache_miss_budget":-1}', "invalid_value"),
        (b'{"schema_version":1,"cache_miss_budget":1.5}', "invalid_value"),
        (b'{"schema_version":1,"cache_miss_budget":"1"}', "invalid_value"),
        (b'{"schema_version":1,"cache_miss_budget":null}', "invalid_value"),
    ],
)
def test_system_settings_closed_v1_parser_rejects_invalid_documents(
    monkeypatch, tmp_path, raw, reason
):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    agent, _events = _settings_agent(tmp_path)
    path = tmp_path / "settings" / "system.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)

    read = system_settings._read_settings(agent)

    assert read.budget is None
    assert read.problem == reason
    assert read.problem_signature.startswith(f"{reason}:")


def test_system_settings_rejects_non_regular_and_bounds_read(
    monkeypatch, tmp_path
):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    agent, events = _settings_agent(tmp_path)
    path = tmp_path / "settings" / "system.json"
    path.mkdir(parents=True)

    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000
    assert events[-1][1]["reason"] == "not_regular"

    path.rmdir()
    path.write_bytes(b"x" * (system_settings.SYSTEM_SETTINGS_MAX_BYTES + 1))
    real_open = Path.open

    def guarded_open(self, *args, **kwargs):
        if self == path:
            raise AssertionError("oversized settings file must not be opened")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000
    assert events[-1][1]["reason"] == "oversize"


def test_system_settings_valid_env_bypasses_file_and_diagnostic(
    monkeypatch, tmp_path
):
    path = tmp_path / "settings" / "system.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    agent, events = _settings_agent(tmp_path)
    reads = []

    def forbidden_read(_agent):
        reads.append(True)
        raise AssertionError("valid env must bypass System file")

    monkeypatch.setattr(system_settings, "_read_settings", forbidden_read)
    monkeypatch.setenv(system_settings.CACHE_MISS_BUDGET_ENV, "3000000")

    assert system_settings.resolve_cache_miss_budget(agent) == 3_000_000
    assert reads == []
    assert events == []


@pytest.mark.parametrize("bad", ["abc", "True", "0", "-5", ""])
def test_system_settings_invalid_env_is_unset(monkeypatch, tmp_path, bad):
    _write_budget_settings(tmp_path, 250_000)
    agent, events = _settings_agent(tmp_path)
    monkeypatch.setenv(system_settings.CACHE_MISS_BUDGET_ENV, bad)

    assert system_settings.resolve_cache_miss_budget(agent) == 250_000
    assert events == []


def test_system_settings_invalid_diagnostic_is_bounded_deduped_and_never_rewrites(
    monkeypatch, tmp_path
):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    agent, events = _settings_agent(tmp_path)
    path = tmp_path / "settings" / "system.json"
    path.parent.mkdir(parents=True)
    raw = b'{"schema_version":1,"cache_miss_budget":"do-not-log-this-value"}'
    path.write_bytes(raw)

    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000
    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000

    assert path.read_bytes() == raw
    assert events == [
        (
            "cache_miss_budget_settings_invalid",
            {
                "settings_path": "settings/system.json",
                "reason": "invalid_value",
                "fallback_budget": 2_000_000,
            },
        )
    ]
    assert "do-not-log-this-value" not in json.dumps(events)
    assert str(tmp_path) not in json.dumps(events)


def test_system_settings_valid_or_missing_snapshot_clears_problem_signature(
    monkeypatch, tmp_path
):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    agent, events = _settings_agent(tmp_path)
    path = tmp_path / "settings" / "system.json"
    path.parent.mkdir(parents=True)
    invalid = b'{"schema_version":1,"cache_miss_budget":false}'

    path.write_bytes(invalid)
    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000
    _write_budget_settings(tmp_path, 123)
    assert system_settings.resolve_cache_miss_budget(agent) == 123
    path.write_bytes(invalid)
    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000

    path.unlink()
    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000
    path.write_bytes(invalid)
    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000

    assert [event for event, _fields in events] == [
        "cache_miss_budget_settings_invalid",
        "cache_miss_budget_settings_invalid",
        "cache_miss_budget_settings_invalid",
    ]


def test_system_settings_atomic_replacement_is_rejected_as_unstable(
    monkeypatch, tmp_path
):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    agent, events = _settings_agent(tmp_path)
    path = _write_budget_settings(tmp_path, 111)
    replacement = path.with_name("replacement.json")
    replacement.write_text(
        json.dumps({"schema_version": 1, "cache_miss_budget": 222}),
        encoding="utf-8",
    )
    real_lstat = Path.lstat
    calls = 0

    def replacing_lstat(self):
        nonlocal calls
        if self == path:
            calls += 1
            if calls == 2:
                replacement.replace(path)
        return real_lstat(self)

    monkeypatch.setattr(Path, "lstat", replacing_lstat)

    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000
    assert events == [
        (
            "cache_miss_budget_settings_invalid",
            {
                "settings_path": "settings/system.json",
                "reason": "unstable_read",
                "fallback_budget": 2_000_000,
            },
        )
    ]
    # The next stable snapshot sees the replacement as one coherent document.
    assert system_settings.resolve_cache_miss_budget(agent) == 222


def test_system_settings_parallel_invalid_snapshot_logs_once(monkeypatch, tmp_path):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    agent, events = _settings_agent(tmp_path)
    path = tmp_path / "settings" / "system.json"
    path.parent.mkdir(parents=True)
    path.write_text("{", encoding="utf-8")
    workers = 8
    barrier = threading.Barrier(workers)

    def resolve():
        barrier.wait(timeout=5)
        return system_settings.resolve_cache_miss_budget(agent)

    with ThreadPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(lambda _index: resolve(), range(workers)))

    assert results == [2_000_000] * workers
    assert events == [
        (
            "cache_miss_budget_settings_invalid",
            {
                "settings_path": "settings/system.json",
                "reason": "malformed_json",
                "fallback_budget": 2_000_000,
            },
        )
    ]


def test_system_manual_contains_declared_ltp_profile_and_budget_settings_contract():
    """The canonical source manual teaches its LTP and settings obligations."""
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
        '{"schema_version": 1, "cache_miss_budget": 2000000}',
        "LINGTAI_CACHE_MISS_BUDGET=3000000",
        "fixed default `2,000,000`",
        "cache_miss_budget_settings_invalid",
        "Only a successful molt",
        "never blocks a request",
        "<agent-workdir>/.notification/system.json",
        "Legacy `init.json` `manifest.cache_miss_budget` is schema-unknown ignored",
    ):
        assert required in body
    assert "no `settings/system.json` and no per-action settings file" not in body


def test_cache_miss_budget_docs_keep_new_owner_and_default_in_lockstep():
    root = Path(__file__).parents[1]
    relative_paths = (
        "ENVIRONMENT_VARIABLES.md",
        "src/lingtai/ANATOMY.md",
        "src/lingtai/kernel/ANATOMY.md",
        "src/lingtai/prompts/substrate/substrate.md",
        "src/lingtai/prompts/procedures/procedures.md",
        "src/lingtai/prompts/meta_guidance/catalog/token_efficiency.md",
        "src/lingtai/tools/system/ANATOMY.md",
        "src/lingtai/tools/system/CONTRACT.md",
        "src/lingtai/intrinsic_skills/system-manual/SKILL.md",
        "src/lingtai/tools/context/manual/SKILL.md",
        "src/lingtai/intrinsic_skills/system-manual/reference/refresh-precheck/SKILL.md",
    )
    stale_phrases = (
        "default 1,000,000",
        "default 1_000_000",
        "via `manifest.cache_miss_budget`",
        "then `config.cache_miss_budget`",
        "agent._config.cache_miss_budget",
        "no `settings/system.json`",
    )

    for relative in relative_paths:
        body = (root / relative).read_text(encoding="utf-8")
        for stale in stale_phrases:
            assert stale not in body, f"{relative} still contains {stale!r}"

    context_manual = " ".join(
        (root / "src/lingtai/tools/context/manual/SKILL.md")
        .read_text(encoding="utf-8")
        .split()
    )
    for required in (
        "<agent-workdir>/settings/system.json",
        '{"schema_version": 1, "cache_miss_budget": 2000000}',
        "LINGTAI_CACHE_MISS_BUDGET=3000000",
        "fixed default `2,000,000`",
        "Only a successful molt",
        "resets the cycle",
        ".notification/system.json",
        "schema-unknown ignored",
    ):
        assert required in context_manual

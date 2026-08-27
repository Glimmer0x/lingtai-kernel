"""Focused vertical proof for the official System declared-host plugin."""
from __future__ import annotations

import json
import re
from inspect import signature
from pathlib import Path

import pytest

from lingtai.agent import Agent
from lingtai.adapters.tool_plugin_host import agent_host_ports
from lingtai.kernel.state import AgentState
from lingtai.kernel.tool_plugin import ToolPluginHost
from lingtai.tools.system import DECLARATION, get_schema, handle as handle_system
from lingtai.tools.system import settings as system_settings
from tests._service_helpers import make_gemini_mock_service


def _write_init(
    workdir: Path,
    *,
    manifest: dict | None = None,
    root: dict | None = None,
) -> Path:
    effective_manifest = {
        "llm": {"provider": "gemini", "model": "gemini-test"},
    }
    if manifest:
        effective_manifest.update(manifest)
    data = {"manifest": effective_manifest, "covenant": "", "pad": ""}
    if root:
        data.update(root)
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / "init.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_system_declaration_is_static_and_the_real_agent_mounts_it_once(tmp_path):
    """System keeps its surface while lifecycle/identity enter only through ports."""
    assert DECLARATION.name == "system"
    assert DECLARATION.public_actions == (
        "refresh", "sleep", "lull", "interrupt", "suspend", "cpr", "clear",
        "nirvana", "presets", "name_set", "name_nickname", "settings", "manual",
    )
    assert DECLARATION.requires == ("workdir", "system_runtime", "identity")
    assert get_schema()["properties"]["action"]["enum"] == list(DECLARATION.public_actions)

    workdir = tmp_path / "agent"
    _write_init(workdir)
    agent = Agent(
        service=make_gemini_mock_service(),
        working_dir=workdir,
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
        assert (
            workdir
            / ".library"
            / "intrinsic"
            / "capabilities"
            / "system-manual"
            / "reference"
            / "settings-inventory"
            / "SKILL.md"
        ).is_file()
        settings = handler({"action": "settings", "input": {}, "reasoning": "inventory"})
        assert tuple(row["key"] for row in settings["settings"]) == (
            system_settings.SYSTEM_SETTING_KEYS
        )

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


def _settings_call(workdir: Path, action_input: dict) -> dict:
    return handle_system(
        _settings_agent(workdir),
        {"action": "settings", "input": action_input, "reasoning": "test"},
    )


def _clear_system_setting_env(monkeypatch) -> None:
    for name in system_settings.SYSTEM_ENVIRONMENT_SETTING_OWNERS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


def test_system_settings_inventory_has_exact_public_contract(monkeypatch, tmp_path):
    _clear_system_setting_env(monkeypatch)
    init_path = _write_init(tmp_path)
    before = init_path.read_bytes()
    result = _settings_call(tmp_path, {})
    rows = result["settings"]
    assert tuple(row["key"] for row in rows) == system_settings.SYSTEM_SETTING_KEYS
    assert len(rows) == len({row["key"] for row in rows}) == 60
    for row in rows:
        assert tuple(row) == (
            "key", "current", "default", "configurable", "comment",
        )
    assert {row["key"] for row in rows if not row["configurable"]} == {
        "agent_name",
        "llm.codex_session_anchor",
    }
    assert {row["comment"] for row in rows} == {
        "system-manual#cache-miss-budget",
        "system-manual/reference/settings-inventory#root-and-manifest-inputs",
        "system-manual/reference/settings-inventory#llm-and-provider-inputs",
        "system-manual/reference/settings-inventory#kernel-environment-controls",
    }
    by_key = {row["key"]: row for row in rows}
    expected_projected_defaults = {
        "cache_miss_budget": system_settings.DEFAULT_CACHE_MISS_BUDGET,
        **{
            spec.key: "<redacted>" if spec.sensitive else spec.default
            for spec in system_settings.SYSTEM_INIT_SETTING_SPECS
        },
        **{
            spec.key: "<redacted>" if spec.sensitive else spec.default
            for spec in system_settings.SYSTEM_ENVIRONMENT_SETTING_SPECS
        },
    }
    assert {
        key: row["default"] for key, row in by_key.items()
    } == expected_projected_defaults
    assert {
        key: by_key[key]["default"]
        for key in (
            "language",
            "context_limit",
            "summarize_notification_threshold",
            "llm.compact_threshold",
            "llm.reasoning_effort_vocab",
            "llm.api_compat",
            "llm.codex_tui_dir",
            "llm.codex_transport",
        )
    } == {
        "language": "en",
        "context_limit": 272_000,
        "summarize_notification_threshold": 3_000,
        "llm.compact_threshold": None,
        "llm.reasoning_effort_vocab": None,
        "llm.api_compat": None,
        "llm.codex_tui_dir": "<redacted>",
        "llm.codex_transport": "rest",
    }
    assert "pseudo_agent_subscriptions" not in by_key
    assert tuple(by_key).index("llm.codex_tui_dir") < tuple(by_key).index(
        "llm.codex_transport"
    )
    assert by_key["cache_miss_budget"] == {
        "key": "cache_miss_budget",
        "current": 2_000_000,
        "default": 2_000_000,
        "configurable": True,
        "comment": "system-manual#cache-miss-budget",
    }
    assert by_key["language"]["current"] == by_key["language"]["default"] == "en"
    assert by_key["context_limit"]["current"] == 272_000
    assert by_key["max_rpm"]["current"] == by_key["max_rpm"]["default"] == 60
    assert by_key["llm.provider"]["current"] == "gemini"
    assert by_key["llm.model"]["current"] == "gemini-test"
    assert by_key["nudge.repeat_interval_seconds"]["current"] == 86_400.0
    assert by_key["llm.codex_transport"]["current"] == "rest"
    assert DECLARATION.settings is True
    assert _settings_call(tmp_path, {"set": "cache_miss_budget"}) == {
        "status": "failed",
        "error_code": "INVALID_ARGUMENT",
        "message": "unsupported system input field",
    }
    assert init_path.read_bytes() == before
    assert not (tmp_path / system_settings.SYSTEM_SETTINGS_RELATIVE_PATH).exists()


def test_system_budget_uses_env_then_file_then_default(monkeypatch, tmp_path):
    _write_init(tmp_path)
    agent = _settings_agent(tmp_path)
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    assert system_settings.resolve_cache_miss_budget(agent) == 2_000_000

    owner_path = _write_budget(tmp_path)
    assert system_settings.resolve_cache_miss_budget(agent) == 250_000

    monkeypatch.setenv(system_settings.CACHE_MISS_BUDGET_ENV, "bad")
    assert system_settings.resolve_cache_miss_budget(agent) == 250_000
    owner_row = _settings_call(tmp_path, {})["settings"][0]
    assert owner_row == {
        "key": "cache_miss_budget",
        "current": 250_000,
        "default": 2_000_000,
        "configurable": True,
        "comment": "system-manual#cache-miss-budget",
    }

    original_read_text = Path.read_text

    def reject_owner_read(self, *args, **kwargs):
        if self == owner_path:
            raise AssertionError("a valid env value must bypass System JSON")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", reject_owner_read)
    monkeypatch.setenv(system_settings.CACHE_MISS_BUDGET_ENV, "3000000")
    assert system_settings.resolve_cache_miss_budget(agent) == 3_000_000
    assert _settings_call(tmp_path, {})["settings"][0]["current"] == 3_000_000


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
    _write_init(tmp_path)
    path = tmp_path / "settings" / "system.json"
    path.parent.mkdir(parents=True)
    path.write_text(body, encoding="utf-8")
    assert system_settings.resolve_cache_miss_budget(_settings_agent(tmp_path)) == 2_000_000
    assert _settings_call(tmp_path, {}) == {
        "status": "failed",
        "error_code": "SETTINGS_UNAVAILABLE",
        "message": "settings inventory is unavailable",
    }


def test_system_settings_inventory_redacts_owner_io_failures(monkeypatch, tmp_path):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    _write_init(tmp_path)
    path = _write_budget(tmp_path)
    original_read_text = Path.read_text

    def fail_owner_file(self, *args, **kwargs):
        if self == path:
            raise OSError("private-token-at-/secret/operator/path")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_owner_file)
    inventory = _settings_call(tmp_path, {})
    assert inventory == {
        "status": "failed",
        "error_code": "SETTINGS_UNAVAILABLE",
        "message": "settings inventory is unavailable",
    }
    assert "private-token" not in json.dumps(inventory)
    assert "/secret/operator/path" not in json.dumps(inventory)
    assert system_settings.resolve_cache_miss_budget(_settings_agent(tmp_path)) == 2_000_000


def test_system_settings_non_regular_owner_path_is_unavailable(monkeypatch, tmp_path):
    monkeypatch.delenv(system_settings.CACHE_MISS_BUDGET_ENV, raising=False)
    _write_init(tmp_path)
    path = tmp_path / system_settings.SYSTEM_SETTINGS_RELATIVE_PATH
    path.mkdir(parents=True)
    assert _settings_call(tmp_path, {}) == {
        "status": "failed",
        "error_code": "SETTINGS_UNAVAILABLE",
        "message": "settings inventory is unavailable",
    }
    assert path.is_dir()


def test_system_settings_uses_materialized_preset_and_resolved_current_state(
    monkeypatch, tmp_path
):
    _clear_system_setting_env(monkeypatch)
    preset = tmp_path / "selected.json"
    preset.write_text(
        json.dumps(
            {
                "description": {"summary": "selected test route"},
                "manifest": {
                    "llm": {
                        "provider": "custom",
                        "model": "preset-model",
                        "api_compat": "openai",
                        "context_limit": 64_000,
                    },
                    "capabilities": {},
                },
            }
        ),
        encoding="utf-8",
    )
    _write_init(
        tmp_path,
        manifest={
            "llm": {"provider": "gemini", "model": "authored-model"},
            "preset": {
                "active": "selected.json",
                "default": "selected.json",
                "allowed": ["selected.json"],
            },
        },
    )

    rows = {row["key"]: row for row in _settings_call(tmp_path, {})["settings"]}
    assert rows["llm.provider"]["current"] == "custom"
    assert rows["llm.model"]["current"] == "preset-model"
    assert rows["llm.api_compat"]["current"] == "openai"
    assert rows["context_limit"]["current"] == 64_000
    assert rows["preset.active"]["current"] == "<redacted>"


_NULLABLE_LLM_KEYS = (
    "llm.compact_threshold",
    "llm.reasoning_effort_vocab",
    "llm.api_compat",
)


def _assert_nullable_llm_projection(
    monkeypatch,
    tmp_path: Path,
    *,
    provider: str,
    authored: dict,
    current: tuple,
    default: tuple,
) -> None:
    _clear_system_setting_env(monkeypatch)
    _write_init(
        tmp_path,
        manifest={"llm": {"provider": provider, "model": "test", **authored}},
    )
    rows = {row["key"]: row for row in _settings_call(tmp_path, {})["settings"]}
    assert tuple(rows[key]["current"] for key in _NULLABLE_LLM_KEYS) == current
    assert tuple(rows[key]["default"] for key in _NULLABLE_LLM_KEYS) == default


@pytest.mark.parametrize(
    "authored,current",
    (
        ({}, (100_000, "openai", None)),
        (
            {
                "compact_threshold": None,
                "reasoning_effort_vocab": None,
                "api_compat": None,
            },
            (None, "openai", None),
        ),
        (
            {
                "compact_threshold": 4_321,
                "reasoning_effort_vocab": "seven_tier",
                "api_compat": "anthropic",
            },
            (4_321, "seven_tier", None),
        ),
    ),
    ids=("omitted", "null", "authored"),
)
def test_system_settings_nullable_llm_openai_route_current_and_default(
    monkeypatch, tmp_path, authored, current
):
    """Official OpenAI follows _openai and the OpenAIAdapter signature."""
    from lingtai.llm.openai.adapter import OpenAIAdapter

    adapter_signature = signature(OpenAIAdapter.__init__)
    assert adapter_signature.parameters["compact_threshold"].default == 100_000
    assert adapter_signature.parameters["reasoning_effort_vocab"].default == "openai"
    _assert_nullable_llm_projection(
        monkeypatch,
        tmp_path,
        provider="openai",
        authored=authored,
        current=current,
        default=(100_000, "openai", None),
    )


@pytest.mark.parametrize("provider", ("custom", "grok", "qwen", "kimi"))
@pytest.mark.parametrize(
    "authored,current",
    (
        ({}, (100_000, "openai", "openai")),
        (
            {
                "compact_threshold": None,
                "reasoning_effort_vocab": None,
                "api_compat": None,
            },
            (100_000, "openai", "openai"),
        ),
        (
            {
                "compact_threshold": 4_321,
                "reasoning_effort_vocab": "seven_tier",
                "api_compat": "openai",
            },
            (4_321, "seven_tier", "openai"),
        ),
    ),
    ids=("omitted", "null", "authored"),
)
def test_system_settings_nullable_llm_custom_factory_openai_routes(
    monkeypatch, tmp_path, provider, authored, current
):
    """Every name bound to _custom shares its OpenAI-compatible semantics."""
    from lingtai.llm.custom.adapter import create_custom_adapter

    assert signature(create_custom_adapter).parameters["api_compat"].default == "openai"
    _assert_nullable_llm_projection(
        monkeypatch,
        tmp_path,
        provider=provider,
        authored=authored,
        current=current,
        default=(100_000, "openai", "openai"),
    )


@pytest.mark.parametrize("provider", ("custom", "grok", "qwen", "kimi"))
@pytest.mark.parametrize(
    "api_compat",
    ("OPENAI", "unexpected", [], {}),
    ids=("uppercase", "unknown", "list", "object"),
)
def test_system_settings_nullable_llm_custom_fallback_uses_openai_defaults(
    monkeypatch, tmp_path, provider, api_compat
):
    """Unvalidated custom compat values reach OpenAI without forwarded axes."""
    _assert_nullable_llm_projection(
        monkeypatch,
        tmp_path,
        provider=provider,
        authored={
            "api_compat": api_compat,
            "compact_threshold": 4_321,
            "reasoning_effort_vocab": "seven_tier",
        },
        current=(100_000, "openai", api_compat),
        default=(100_000, "openai", "openai"),
    )


@pytest.mark.parametrize(
    "authored",
    (
        {"api_compat": "anthropic"},
        {
            "api_compat": "anthropic",
            "compact_threshold": None,
            "reasoning_effort_vocab": None,
        },
        {
            "api_compat": "anthropic",
            "compact_threshold": 4_321,
            "reasoning_effort_vocab": "seven_tier",
        },
    ),
    ids=("omitted", "null", "authored"),
)
def test_system_settings_nullable_llm_custom_non_openai_route(
    monkeypatch, tmp_path, authored
):
    _assert_nullable_llm_projection(
        monkeypatch,
        tmp_path,
        provider="custom",
        authored=authored,
        current=(None, None, "anthropic"),
        default=(None, None, "openai"),
    )


@pytest.mark.parametrize(
    "authored,current",
    (
        ({}, (None, None, None)),
        (
            {
                "compact_threshold": None,
                "reasoning_effort_vocab": None,
                "api_compat": None,
            },
            (None, None, None),
        ),
        (
            {
                "compact_threshold": 4_321,
                "reasoning_effort_vocab": "seven_tier",
                "api_compat": "openai",
            },
            (4_321, None, None),
        ),
    ),
    ids=("omitted", "null", "authored"),
)
def test_system_settings_nullable_llm_deepseek_route(
    monkeypatch, tmp_path, authored, current
):
    _assert_nullable_llm_projection(
        monkeypatch,
        tmp_path,
        provider="deepseek",
        authored=authored,
        current=current,
        default=(None, None, None),
    )


@pytest.mark.parametrize(
    "authored",
    (
        {},
        {
            "compact_threshold": None,
            "reasoning_effort_vocab": None,
            "api_compat": None,
        },
        {
            "compact_threshold": 4_321,
            "reasoning_effort_vocab": "seven_tier",
            "api_compat": "openai",
        },
    ),
    ids=("omitted", "null", "authored"),
)
def test_system_settings_nullable_llm_gemini_ignored_route(
    monkeypatch, tmp_path, authored
):
    _assert_nullable_llm_projection(
        monkeypatch,
        tmp_path,
        provider="gemini",
        authored=authored,
        current=(None, None, None),
        default=(None, None, None),
    )


@pytest.mark.parametrize("provider", ("codex", "codex-pool", "codex_pool"))
@pytest.mark.parametrize(
    "authored",
    (
        {},
        {
            "compact_threshold": None,
            "reasoning_effort_vocab": None,
            "api_compat": None,
        },
        {
            "compact_threshold": 4_321,
            "reasoning_effort_vocab": "seven_tier",
            "api_compat": "openai",
        },
    ),
    ids=("omitted", "null", "authored"),
)
def test_system_settings_nullable_llm_native_codex_routes_ignore_generic_axes(
    monkeypatch, tmp_path, provider, authored
):
    _assert_nullable_llm_projection(
        monkeypatch,
        tmp_path,
        provider=provider,
        authored=authored,
        current=(None, None, None),
        default=(None, None, None),
    )


def test_system_settings_redacts_sensitive_effective_values(monkeypatch, tmp_path):
    _clear_system_setting_env(monkeypatch)
    prompt_secret = "prompt-secret-sentinel"
    credential_secret = "credential-secret-sentinel"
    header_secret = "header-secret-sentinel"
    path_secret = "private-path-sentinel"
    prompt_file = tmp_path / f"{path_secret}.md"
    prompt_file.write_text(prompt_secret, encoding="utf-8")
    _write_init(
        tmp_path,
        manifest={
            "llm": {
                "provider": "custom",
                "model": "redaction-model",
                "api_key": credential_secret,
                "base_url": f"https://user:{credential_secret}@example.invalid/v1",
                "api_compat": "openai",
                "codex_auth_path": f"secrets/{path_secret}.json",
                "codex_auth_pool_path": f"secrets/{path_secret}-pool.json",
                "codex_base_urls": [f"https://{credential_secret}@example.invalid"],
                "default_headers": {"Authorization": header_secret},
            },
            "admin": {"karma": True, "private": credential_secret},
            "pseudo_agent_subscriptions": [f"../{path_secret}"],
        },
        root={
            "base_prompt": "shadowed-inline-secret",
            "base_prompt_file": prompt_file.name,
            "comment": prompt_secret,
            "env_file": f"config/{path_secret}.env",
            "venv_path": f"runtimes/{path_secret}",
        },
    )

    result = _settings_call(tmp_path, {})
    serialized = json.dumps(result, sort_keys=True)
    for secret in (
        prompt_secret,
        credential_secret,
        header_secret,
        path_secret,
        "shadowed-inline-secret",
    ):
        assert secret not in serialized
    rows = {row["key"]: row for row in result["settings"]}
    for key in (
        "env_file",
        "venv_path",
        "base_prompt",
        "base_prompt_file",
        "comment",
        "admin",
        "llm.api_key",
        "llm.base_url",
        "llm.codex_auth_path",
        "llm.codex_auth_pool_path",
        "llm.codex_base_urls",
        "llm.default_headers",
    ):
        assert rows[key]["current"] == "<redacted>"
        assert rows[key]["default"] == "<redacted>"
    assert "pseudo_agent_subscriptions" not in rows


def test_system_settings_environment_resolution_and_alias_precedence(
    monkeypatch, tmp_path
):
    _clear_system_setting_env(monkeypatch)
    _write_init(tmp_path)
    monkeypatch.setenv("LINGTAI_NUDGE_ENABLED", "off")
    monkeypatch.setenv("LINGTAI_NUDGE_REPEAT_INTERVAL", "30m")
    monkeypatch.setenv("LINGTAI_NUDGE_FOLDER_SIZE_GB", "not-a-number")
    monkeypatch.setenv("LINGTAI_ACTIVE_STUCK_THRESHOLD_S", "12")
    monkeypatch.setenv("LINGTAI_TOOL_PROSE_SECTION_ENABLED", " yes ")
    monkeypatch.setenv("LINGTAI_SYSTEM_PROMPT_PRESSURE_RATIO", "0.75")
    monkeypatch.setenv("LINGTAI_SESSION_STATS_REFRESH_SECONDS", "2.5")
    monkeypatch.setenv("LINGTAI_SESSION_STATS_DAEMON_LIMIT", "7")
    monkeypatch.setenv("LINGTAI_RISKY_ACTION_GATE", "true")
    monkeypatch.setenv("LINGTAI_VERBOSE", "1")
    monkeypatch.setenv("LINGTAI_CODEX_TRANSPORT", "http")
    monkeypatch.setenv("LINGTAI_CODEX_WS", "1")
    monkeypatch.setenv("LINGTAI_CODEX_WS_EPOCH_RESET_TURNS", "4")
    monkeypatch.setenv("LINGTAI_CODEX_RESPONSES_TRACE", "yes")
    monkeypatch.setenv(
        "LINGTAI_CODEX_RESPONSES_TRACE_PATH", "/private/trace-secret-sentinel.jsonl"
    )
    monkeypatch.setenv("LINGTAI_LLM_READ_TIMEOUT", "nan")
    monkeypatch.setenv("LINGTAI_INJECT_REASONING_FALLBACK", "off")

    rows = {row["key"]: row for row in _settings_call(tmp_path, {})["settings"]}
    assert rows["nudge.enabled"]["current"] is False
    assert rows["nudge.repeat_interval_seconds"]["current"] == 1_800.0
    assert rows["nudge.folder_size_gb"]["current"] == 5.0
    assert rows["lifecycle.active_stuck_threshold_seconds"]["current"] == 30.0
    assert rows["prompt.tool_prose_section_enabled"]["current"] is True
    assert rows["prompt.system_prompt_pressure_ratio"]["current"] == 0.75
    assert rows["session_stats.refresh_seconds"]["current"] == 2.5
    assert rows["session_stats.daemon_limit"]["current"] == 7
    assert rows["security.risky_action_gate"]["current"] is True
    assert rows["logging.console_debug"]["current"] is True
    assert rows["llm.codex_transport"]["current"] == "rest"
    assert rows["llm.codex_ws_epoch_reset_turns"]["current"] == 4
    assert rows["llm.codex_responses_trace"]["current"] is True
    assert rows["llm.codex_responses_trace_path"]["current"] == "<redacted>"
    assert rows["llm.read_timeout_seconds"]["current"] == 300.0
    assert rows["llm.inject_reasoning_fallback"]["current"] is False
    assert "trace-secret-sentinel" not in json.dumps(rows)

    monkeypatch.delenv("LINGTAI_CODEX_TRANSPORT")
    monkeypatch.setenv("LINGTAI_CODEX_WS_EPOCH_RESET_TURNS", "invalid")
    rows = {row["key"]: row for row in _settings_call(tmp_path, {})["settings"]}
    assert rows["llm.codex_transport"]["current"] == "websocket"
    assert rows["llm.codex_ws_epoch_reset_turns"]["current"] == 0


def test_system_settings_codex_tui_dir_omitted_and_explicit_are_fully_redacted(
    monkeypatch, tmp_path
):
    _clear_system_setting_env(monkeypatch)
    _write_init(tmp_path)

    default_path = str(Path("~/.lingtai-tui").expanduser())
    if system_settings._environment_current("codex_tui_dir", tmp_path) != default_path:
        pytest.fail("Codex TUI default resolution drifted")
    omitted = _settings_call(tmp_path, {})
    omitted_row = {
        row["key"]: row for row in omitted["settings"]
    }["llm.codex_tui_dir"]
    assert omitted_row["current"] == omitted_row["default"] == "<redacted>"
    assert default_path not in json.dumps(omitted)

    explicit_path = str(tmp_path / "private-codex-auth-sentinel")
    monkeypatch.setenv("LINGTAI_TUI_DIR", explicit_path)
    if system_settings._environment_current("codex_tui_dir", tmp_path) != explicit_path:
        pytest.fail("Codex TUI environment precedence drifted")
    explicit = _settings_call(tmp_path, {})
    explicit_row = {
        row["key"]: row for row in explicit["settings"]
    }["llm.codex_tui_dir"]
    assert explicit_row["current"] == explicit_row["default"] == "<redacted>"
    assert explicit_path not in json.dumps(explicit)


def test_system_settings_malformed_effective_source_fails_complete_action(
    monkeypatch, tmp_path
):
    _clear_system_setting_env(monkeypatch)
    init_path = _write_init(tmp_path)
    init_path.write_text('{"manifest":', encoding="utf-8")
    result = _settings_call(tmp_path, {})
    assert result == {
        "status": "failed",
        "error_code": "SETTINGS_UNAVAILABLE",
        "message": "settings inventory is unavailable",
    }
    assert "manifest" not in json.dumps(result)


def test_system_settings_malformed_risky_gate_document_fails_complete_action(
    monkeypatch, tmp_path
):
    _clear_system_setting_env(monkeypatch)
    _write_init(tmp_path)
    gate_path = tmp_path / ".security" / "gate_config.json"
    gate_path.parent.mkdir(parents=True)
    gate_path.write_text("[]", encoding="utf-8")
    result = _settings_call(tmp_path, {})
    assert result == {
        "status": "failed",
        "error_code": "SETTINGS_UNAVAILABLE",
        "message": "settings inventory is unavailable",
    }
    assert str(gate_path) not in json.dumps(result)


def test_system_settings_classification_covers_init_and_environment_registries():
    from lingtai.init_schema import LLM_KNOWN, MANIFEST_KNOWN, TOP_KNOWN

    included = {spec.pointer for spec in system_settings.SYSTEM_INIT_SETTING_SPECS}
    init_excluded = (
        system_settings.SYSTEM_INIT_CONCRETE_TOOL_EXCLUSIONS
        | system_settings.SYSTEM_INIT_INERT_OR_COMPATIBILITY_EXCLUSIONS
    )
    assert not included & init_excluded

    for key in TOP_KNOWN - {"manifest"}:
        assert f"/{key}" in included | init_excluded, key
    for key in MANIFEST_KNOWN - {"llm"}:
        pointer = f"/manifest/{key}"
        assert pointer in included | init_excluded or any(
            candidate.startswith(f"{pointer}/") for candidate in included | init_excluded
        ), key
    for key in LLM_KNOWN:
        assert f"/manifest/llm/{key}" in included | init_excluded, key

    for required_non_setting in (
        "/pad",
        "/pad_file",
        "/manifest/activeness",
        "/manifest/pseudo_agent_subscriptions",
        "/manifest/max_turns",
        "/manifest/context_serialization_enabled",
        "/manifest/llm/codex_thread_salt",
        "/manifest/llm/context_limit",
    ):
        assert required_non_setting in init_excluded

    classification = system_settings.SYSTEM_ENVIRONMENT_CLASSIFICATION
    assert classification["system"] == set(
        system_settings.SYSTEM_ENVIRONMENT_SETTING_OWNERS
    )
    assert "LINGTAI_TUI_DIR" in classification["system"]
    assert all(classification.values())
    assert sum(map(len, classification.values())) == len(
        set().union(*classification.values())
    )

    registered_classes = {
        name: values
        for name, values in classification.items()
        if name != "unregistered_concrete_tool"
    }
    registry_body = (
        Path(__file__).parents[1] / "ENVIRONMENT_VARIABLES.md"
    ).read_text(encoding="utf-8")
    registry_names = set(
        re.findall(r"^\| `(LINGTAI_[^`]+)`", registry_body, flags=re.MULTILINE)
    )
    assert registry_names == set().union(*registered_classes.values())
    assert system_settings.SYSTEM_ENVIRONMENT_SETTING_OWNERS[
        "LINGTAI_CODEX_WS"
    ] == "llm.codex_transport"
    assert system_settings.SYSTEM_ENVIRONMENT_SETTING_OWNERS[
        "LINGTAI_TUI_DIR"
    ] == "llm.codex_tui_dir"
    assert "llm.codex_thread_salt" not in system_settings.SYSTEM_SETTING_KEYS
    assert "pseudo_agent_subscriptions" not in system_settings.SYSTEM_SETTING_KEYS
    assert not any(
        key.startswith(("soul.", "shell.", "daemon.", "notification."))
        for key in system_settings.SYSTEM_SETTING_KEYS
    )


def test_system_settings_manual_projects_environment_classification():
    inventory_manual = (
        Path(__file__).parents[1]
        / "src"
        / "lingtai"
        / "intrinsic_skills"
        / "system-manual"
        / "reference"
        / "settings-inventory"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    system_manual = (
        Path(__file__).parents[1]
        / "src"
        / "lingtai"
        / "intrinsic_skills"
        / "system-manual"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    manual_projection = f"{system_manual}\n{inventory_manual}"

    # The manual is a human projection of the structured owner-local
    # classification, not a second registry parsed for ownership or source use.
    assert {
        name
        for values in system_settings.SYSTEM_ENVIRONMENT_CLASSIFICATION.values()
        for name in values
        if f"`{name}`" not in manual_projection
    } == set()


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
        "### Cache-miss budget",
        "system-manual#cache-miss-budget",
        "read-only SHOW",
        "existing File or",
        "Shell capability",
        'system(action="settings", input={})` again',
    ):
        assert required in body
    assert '"set":"cache_miss_budget"' not in body
    assert '"reset":"cache_miss_budget"' not in body

    refresh_reference = (
        manual_path.parent / "reference" / "refresh-precheck" / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "settings/system.json" in refresh_reference
    assert "`2,000,000` default" in refresh_reference
    assert "Legacy `manifest.cache_miss_budget` is ignored" in refresh_reference
    assert "default 1,000,000" not in refresh_reference

    inventory_reference = (
        manual_path.parent / "reference" / "settings-inventory" / "SKILL.md"
    ).read_text(encoding="utf-8")
    for heading in (
        "## Root and manifest inputs",
        "## LLM and provider inputs",
        "## Kernel environment controls",
        "## Explicit non-settings and exclusions",
    ):
        assert heading in inventory_reference
    for required in (
        "accepted value",
        "Invalid behavior",
        "Redaction",
        "Application timing",
        "Authorized change procedure",
        "active preset over authored init",
        "LINGTAI_CODEX_WS",
        "llm.codex_tui_dir",
        "LINGTAI_TUI_DIR",
        "manifest.pseudo_agent_subscriptions",
        "future Email-owner",
        "fully redact both current and default path lists",
        "Injected or handoff environment exclusions",
        "Build-only environment exclusions",
        "Test-only environment exclusions",
        "manifest.llm.codex_thread_salt",
    ):
        assert required in inventory_reference

    comments = {
        "system-manual#cache-miss-budget",
        *(spec.comment for spec in system_settings.SYSTEM_INIT_SETTING_SPECS),
        "system-manual/reference/settings-inventory#kernel-environment-controls",
    }
    assert comments == {
        "system-manual#cache-miss-budget",
        "system-manual/reference/settings-inventory#root-and-manifest-inputs",
        "system-manual/reference/settings-inventory#llm-and-provider-inputs",
        "system-manual/reference/settings-inventory#kernel-environment-controls",
    }

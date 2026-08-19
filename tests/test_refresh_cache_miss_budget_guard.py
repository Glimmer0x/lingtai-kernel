"""Tests for the cache-miss budget guard on ``system(action='refresh')``.

The since-last-molt cache-miss total is read from the CUMULATIVE token
counters, which deliberately survive ``restore_token_state`` — so a refresh
(same identity, preserved conversation) can never lower it. It replays the
preserved context at full cold-cache cost and returns with the budget still
exhausted. The tool must therefore refuse and redirect to
``context(action='molt')`` instead of performing a recovery it cannot deliver.

Below budget, refresh behavior is unchanged. An agent with no ``context``
intrinsic cannot molt and is never refused.
"""
import json
from pathlib import Path

from lingtai.tools.registry import INTRINSICS as _TEST_INTRINSICS
from tests._workdir_lease_helpers import make_test_lease
from tests._snapshot_helpers import make_test_snapshot_port, make_test_source_revision_port
from tests._lifecycle_clock_helpers import make_test_lifecycle_clock
from tests._notification_store_helpers import notification_store_for
from tests._agent_presence_helpers import make_test_presence_store

DEFAULT_BUDGET = 1_000_000


def _build_workdir(wd: Path) -> None:
    wd.mkdir(parents=True, exist_ok=True)
    env = wd / ".env"
    env.write_text("PLACEHOLDERKEY=sk-test\n")
    init = {
        "manifest": {
            "agent_name": "test", "language": "en",
            "llm": {"provider": "PLACEHOLDER", "model": "PLACEHOLDER",
                    "api_key": None, "api_key_env": "PLACEHOLDERKEY"},
            "capabilities": {},
            "context_limit": 200000,
            "soul": {"delay": 120}, "stamina": 3600,
            "molt_pressure": 0.8, "molt_prompt": "", "max_turns": 50,
            "admin": {"karma": True}, "streaming": False,
        },
        "principle": "p", "covenant": "c", "pad": "", "lingtai": "",
        "soul": "",
        "env_file": str(env),
    }
    (wd / "init.json").write_text(json.dumps(init))


def _make_test_agent(tmp_path, *, intrinsics=None):
    """BaseAgent stand-in with stubbed ``_perform_refresh``/``get_token_usage``."""
    from lingtai.kernel.base_agent import BaseAgent
    from unittest.mock import MagicMock

    svc = MagicMock()
    svc.get_adapter.return_value = MagicMock()
    svc.provider = "gemini"
    svc.model = "gemini-test"
    wd = tmp_path / "test"
    _build_workdir(wd)
    return BaseAgent(
        intrinsics=_TEST_INTRINSICS if intrinsics is None else intrinsics,
        service=svc, agent_name="test", working_dir=wd,
        workdir_lease=make_test_lease(), snapshot_port=make_test_snapshot_port(),
        agent_presence=make_test_presence_store(),
        lifecycle_clock=make_test_lifecycle_clock(),
        source_revision_port=make_test_source_revision_port(),
        notification_store=notification_store_for(wd),
    )


def _stub_usage(agent, monkeypatch, *, input_tokens: int, cached_tokens: int) -> None:
    """Stub the cumulative counters the guard reads (cache miss = input - cached)."""
    monkeypatch.setattr(agent, "get_token_usage", lambda: {
        "input_tokens": input_tokens, "cached_tokens": cached_tokens,
        "output_tokens": 0, "thinking_tokens": 0, "total_tokens": 0,
        "api_calls": 0, "ctx_total_tokens": 1000,
        "ctx_system_tokens": 0, "ctx_tools_tokens": 0, "ctx_history_tokens": 1000,
    })


def _record_refresh(agent, monkeypatch) -> list:
    calls: list = []
    monkeypatch.setattr(agent, "_perform_refresh", lambda: calls.append(True))
    return calls


def _record_log(agent, monkeypatch) -> list:
    events: list = []
    real_log = agent._log
    monkeypatch.setattr(
        agent, "_log",
        lambda evt, **kw: (events.append((evt, kw)), real_log(evt, **kw))[1],
    )
    return events


def test_refresh_refused_when_cache_miss_budget_exhausted(tmp_path, monkeypatch):
    """The reported loop: refresh at/above budget is refused, not performed."""
    agent = _make_test_agent(tmp_path)
    # 1_100_000 cache miss against the default 1_000_000 budget.
    _stub_usage(agent, monkeypatch, input_tokens=1_200_000, cached_tokens=100_000)
    perform_calls = _record_refresh(agent, monkeypatch)
    log_events = _record_log(agent, monkeypatch)

    result = agent._intrinsics["system"]({"action": "refresh", "input": {"reason": "recover"}})

    assert result["status"] == "error"
    msg = result["message"]
    assert "1100000" in msg and "1000000" in msg
    # The redirect must name the only action that actually clears the budget.
    assert "molt" in msg.lower()
    assert perform_calls == []  # refresh NOT performed
    assert "refresh_refused_cache_miss_budget" in [e for e, _ in log_events]
    refusal = next(kw for e, kw in log_events if e == "refresh_refused_cache_miss_budget")
    assert refusal == {"cache_miss_tokens": 1_100_000, "cache_miss_budget": DEFAULT_BUDGET}


def test_refresh_refused_at_cache_miss_budget_boundary(tmp_path, monkeypatch):
    """The inclusive budget boundary is refused, matching the molt reminder."""
    agent = _make_test_agent(tmp_path)
    _stub_usage(agent, monkeypatch, input_tokens=DEFAULT_BUDGET, cached_tokens=0)
    perform_calls = _record_refresh(agent, monkeypatch)

    result = agent._intrinsics["system"]({"action": "refresh", "input": {}})

    assert result["status"] == "error"
    assert perform_calls == []


def test_refresh_proceeds_when_cache_miss_is_below_budget(tmp_path, monkeypatch):
    """Existing refresh behavior below budget is unchanged."""
    agent = _make_test_agent(tmp_path)
    _stub_usage(agent, monkeypatch, input_tokens=DEFAULT_BUDGET - 1, cached_tokens=0)
    perform_calls = _record_refresh(agent, monkeypatch)

    result = agent._intrinsics["system"]({"action": "refresh", "input": {"reason": "config change"}})

    assert result["status"] == "ok"
    assert perform_calls == [True]


def test_refusal_precedes_any_preset_side_effect(tmp_path, monkeypatch):
    """An exhausted budget refuses before the preset gates touch anything.

    The guard runs ahead of the allowed-list check, the context-limit check,
    and activation, so a refused refresh activates no preset and rewrites no
    ``manifest.preset.default``.
    """
    agent = _make_test_agent(tmp_path)
    _stub_usage(agent, monkeypatch, input_tokens=2_000_000, cached_tokens=0)
    perform_calls = _record_refresh(agent, monkeypatch)

    def _boom(*_args, **_kwargs):
        raise AssertionError("preset activation must not run on a refused refresh")

    monkeypatch.setattr(agent, "_activate_preset", _boom)
    monkeypatch.setattr(agent, "_activate_default_preset", _boom)
    init_before = (agent._working_dir / "init.json").read_text()

    result = agent._intrinsics["system"]({
        "action": "refresh",
        "input": {"preset": str(tmp_path / "ghost.json")},
    })

    assert result["status"] == "error"
    # The budget refusal, not the allowed-list refusal.
    assert "cache-miss budget" in result["message"]
    assert "allowed" not in result["message"]
    assert perform_calls == []
    assert (agent._working_dir / "init.json").read_text() == init_before


def test_env_override_moves_the_refusal_threshold_both_ways(tmp_path, monkeypatch):
    """The refusal reads the same budget the ``molt now`` reminder reads.

    ``LINGTAI_CACHE_MISS_BUDGET`` is live-read at every resolution
    (``meta_block._resolve_cache_miss_budget``), so a lowered override refuses
    a total the default would allow, and a raised override allows one the
    default would refuse.
    """
    agent = _make_test_agent(tmp_path)
    _stub_usage(agent, monkeypatch, input_tokens=20_000, cached_tokens=0)
    perform_calls = _record_refresh(agent, monkeypatch)

    monkeypatch.setenv("LINGTAI_CACHE_MISS_BUDGET", "10000")
    refused = agent._intrinsics["system"]({"action": "refresh", "input": {}})
    assert refused["status"] == "error"
    assert "10000" in refused["message"]
    assert perform_calls == []

    monkeypatch.setenv("LINGTAI_CACHE_MISS_BUDGET", "10000000")
    allowed = agent._intrinsics["system"]({"action": "refresh", "input": {}})
    assert allowed["status"] == "ok"
    assert perform_calls == [True]


def test_refresh_not_refused_when_context_intrinsic_is_absent(tmp_path, monkeypatch):
    """No molt action → no refusal; the guard must never trap such an agent."""
    agent = _make_test_agent(
        tmp_path,
        intrinsics={k: v for k, v in _TEST_INTRINSICS.items() if k != "context"},
    )
    assert "context" not in agent._intrinsics
    _stub_usage(agent, monkeypatch, input_tokens=5_000_000, cached_tokens=0)
    perform_calls = _record_refresh(agent, monkeypatch)

    result = agent._intrinsics["system"]({"action": "refresh", "input": {}})

    assert result["status"] == "ok"
    assert perform_calls == [True]


def test_refresh_proceeds_when_cache_usage_is_unreadable(tmp_path, monkeypatch):
    """A broken usage read must not trap an otherwise valid refresh."""
    agent = _make_test_agent(tmp_path)
    monkeypatch.setattr(agent, "get_token_usage", lambda: (_ for _ in ()).throw(RuntimeError()))
    perform_calls = _record_refresh(agent, monkeypatch)

    result = agent._intrinsics["system"]({"action": "refresh", "input": {}})

    assert result["status"] == "ok"
    assert perform_calls == [True]

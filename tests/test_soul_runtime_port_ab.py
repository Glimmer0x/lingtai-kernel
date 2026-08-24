"""Focused Soul A/B boundary proofs.

The implementation modules consume the structural SoulRuntimePort directly.
Only the package root adapts a legacy whole Agent for kernel hooks/tests.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.agent import Agent
from lingtai.tools import soul
from lingtai.tools.soul import consultation, config
from tests._service_helpers import make_gemini_mock_service


class _StructuralRuntime:
    """Small structural port double; deliberately has no Agent attributes."""

    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir
        self.config = SimpleNamespace(
            language="en",
            consultation_past_count=2,
            context_limit=200_000,
            retry_timeout=1.0,
            model=None,
            provider=None,
            soul_voice="inner",
            soul_voice_prompt="",
        )
        self.chat = None
        self.service = None
        self.session = None
        self.shutdown = threading.Event()
        self.idle_event = threading.Event()
        self.soul_delay = 120.0
        self.soul_timer = None
        self.fire_lock = threading.Lock()
        self.notification_store = None
        self.notification_fingerprint = None
        self.appendix_ids_by_source: dict[str, str] = {}
        self.restart_calls = 0
        self.logs: list[tuple[str, dict]] = []

    def restart_soul_timer(self) -> None:
        self.restart_calls += 1

    def log(self, event: str, **fields) -> None:
        self.logs.append((event, fields))


def test_ab_consumers_do_not_embed_an_agent_bridge() -> None:
    """A/B keeps whole-Agent adaptation singular at the package root."""
    source_dir = Path(__file__).parents[1] / "src" / "lingtai" / "tools" / "soul"
    forbidden = ("agent_soul_runtime", "AgentSoulRuntimeAdapter", "_as_runtime")
    for name in ("config.py", "flow.py", "inquiry.py", "consultation.py"):
        source = (source_dir / name).read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), name


def test_config_and_diary_consume_structural_runtime_directly(tmp_path, monkeypatch) -> None:
    """The config and consultation consumers operate on port vocabulary."""
    runtime = _StructuralRuntime(tmp_path)
    (tmp_path / "init.json").write_text(
        json.dumps({"manifest": {"soul": {}}}), encoding="utf-8"
    )
    monkeypatch.delenv("LINGTAI_SOUL_FLOW_ENABLED", raising=False)

    result = config._handle_config(runtime, {"delay_seconds": 60})

    assert result["status"] == "ok"
    assert result["new"] == {"delay_seconds": 60.0}
    assert result["soul_flow_enabled"] is False
    assert runtime.soul_delay == 60.0
    assert runtime.restart_calls == 1
    persisted = json.loads((tmp_path / "init.json").read_text(encoding="utf-8"))
    assert persisted["manifest"]["soul"]["delay"] == 60.0

    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "events.jsonl").write_text(
        json.dumps({"type": "diary", "ts": 1, "text": "a structural thought"}) + "\n",
        encoding="utf-8",
    )
    diary = consultation._render_current_diary(runtime)
    assert "diary" in diary
    assert "a structural thought" in diary


def test_declaration_binds_structural_port_and_persists_config(tmp_path, monkeypatch) -> None:
    """The official binder dispatches through a non-Agent structural port."""
    from lingtai.kernel.tool_plugin import ToolPluginHost

    runtime = _StructuralRuntime(tmp_path)
    (tmp_path / "init.json").write_text(
        json.dumps({"manifest": {"soul": {}}}), encoding="utf-8"
    )
    workdir = SimpleNamespace(path=tmp_path)
    host = ToolPluginHost.grant(
        soul.DECLARATION,
        {"workdir": workdir, "soul_runtime": runtime},
    )
    bound = soul.DECLARATION.bind(host)

    monkeypatch.delenv("LINGTAI_SOUL_FLOW_ENABLED", raising=False)
    result = bound.handler(
        {
            "action": "config",
            "input": {"delay_seconds": 75, "consultation_past_count": None},
            "reasoning": "prove structural SoulRuntimePort dispatch",
        }
    )

    assert result["status"] == "ok"
    assert result["new"] == {"delay_seconds": 75.0}
    assert result["soul_flow_enabled"] is False
    assert runtime.soul_delay == 75.0
    persisted = json.loads((tmp_path / "init.json").read_text(encoding="utf-8"))
    assert persisted["manifest"]["soul"]["delay"] == 75.0


@pytest.fixture
def real_agent(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="soul-ab-real-agent",
        working_dir=tmp_path / "agent",
    )
    try:
        yield agent
    finally:
        agent.stop(timeout=1.0)


def test_root_bridge_preserves_real_agent_compatibility(real_agent, monkeypatch) -> None:
    """A real Agent still works when entered through Soul's explicit root."""
    monkeypatch.delenv("LINGTAI_SOUL_FLOW_ENABLED", raising=False)

    result = soul.handle(
        real_agent,
        {
            "action": "config",
            "input": {"delay_seconds": 60, "consultation_past_count": None},
            "reasoning": "exercise the root compatibility bridge",
        },
    )

    assert result["status"] == "ok"
    assert result["new"] == {"delay_seconds": 60.0}
    assert result["soul_flow_enabled"] is False
    assert real_agent._soul_delay == 60.0

"""Web-owned composition-port and manual-contract regressions.

These tests stay beside the Web family while shared host and manual fixtures
are reserved for serialized integration.  They prove the local typed boundary,
its negative setup cases, and the real Agent bind path.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from lingtai.agent import Agent
from tests._service_helpers import make_gemini_mock_service
from lingtai.tools.web_search import (
    WebComposition,
    WebCompositionPort,
    _EngineSpec,
    _bind,
    setup,
)


class _BrowserPort:
    pass


class _Workdir:
    def __init__(self, path: Path) -> None:
        self.path = path


class _ProviderIdentity:
    provider = "gemini"


def _composition(tmp_path: Path) -> WebComposition:
    return WebComposition(
        browser_port=_BrowserPort(),
        specs={"duckduckgo": _EngineSpec("duckduckgo", provider="duckduckgo")},
        default_engine="duckduckgo",
        default_source="built_in_default",
        legacy_fallback_from=None,
    )


def _host(tmp_path: Path, value: object) -> SimpleNamespace:
    return SimpleNamespace(
        workdir=_Workdir(tmp_path),
        provider_identity=_ProviderIdentity(),
        runtime=SimpleNamespace(value=value),
    )


def test_web_composition_port_is_narrow_and_publishes_one_manager(tmp_path):
    value = _composition(tmp_path)
    assert isinstance(value, WebCompositionPort)
    assert value.specs["duckduckgo"].provider == "duckduckgo"
    assert value.manager is None

    bound = _bind(_host(tmp_path, value))
    assert bound.name == "web"
    assert value.manager is not None


def test_web_bind_missing_host_port_fails_loudly(tmp_path):
    host = SimpleNamespace(
        workdir=_Workdir(tmp_path),
        provider_identity=_ProviderIdentity(),
    )
    with pytest.raises(TypeError, match="granted WebCompositionPort"):
        _bind(host)


def test_web_bind_wrong_host_port_fails_typed_contract(tmp_path):
    with pytest.raises(TypeError, match="typed WebCompositionPort"):
        _bind(_host(tmp_path, object()))


def test_web_real_agent_bind_returns_manager_and_preserves_manual_surface(tmp_path):
    agent = Agent(
        service=make_gemini_mock_service(),
        agent_name="web-composition-port",
        working_dir=tmp_path / "agent",
        capabilities={},
    )
    try:
        manual_dir = agent.working_dir / ".library" / "intrinsic" / "capabilities" / "web"
        manual_dir.mkdir(parents=True, exist_ok=True)
        (manual_dir / "SKILL.md").write_text("# Web manual\n", encoding="utf-8")
        manager = setup(agent, browser_port=_BrowserPort())
        assert manager._family.has_manual()
        assert agent.official_tool_plugins["web"].name == "web"
        result = manager.handle(
            {"action": "manual", "input": {}, "reasoning": "load guidance"}
        )
        assert result["status"] == "ok"
        assert result["manual"] == "# Web manual\n"
    finally:
        agent.stop(timeout=1.0)


def _real_web_agent(tmp_path: Path) -> Agent:
    return Agent(
        service=make_gemini_mock_service(),
        agent_name="web-manual-contract",
        working_dir=tmp_path / "agent",
        capabilities={},
    )


def _write_web_manual(agent: Agent, body: str) -> Path:
    path = agent.working_dir / ".library" / "intrinsic" / "capabilities" / "web" / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_web_manual_child_returns_canonical_result_before_flat_adaptation(tmp_path):
    agent = _real_web_agent(tmp_path)
    try:
        path = _write_web_manual(agent, "# Web manual\nFull body here.")
        manager = setup(agent, browser_port=_BrowserPort())
        envelope = {"action": "manual", "input": {}, "reasoning": "load guidance"}
        canonical = manager._family.handle(envelope)
        assert canonical["status"] == "ok"
        assert canonical["content"] == [{"type": "text", "text": "# Web manual\nFull body here."}]
        assert canonical["structuredContent"] == {"manual_path": str(path)}
        assert "manual" not in canonical

        flat = manager.handle(envelope)
        assert flat["status"] == "ok"
        assert flat["manual"] == "# Web manual\nFull body here."
        assert flat["manual_path"] == str(path)
        assert "content" not in flat
    finally:
        agent.stop(timeout=1.0)


def test_web_manual_child_missing_file_preserves_degraded_public_shape(tmp_path):
    agent = _real_web_agent(tmp_path)
    try:
        path = agent.working_dir / ".library" / "intrinsic" / "capabilities" / "web" / "SKILL.md"
        path.unlink(missing_ok=True)
        manager = setup(agent, browser_port=_BrowserPort())
        result = manager.handle(
            {"action": "manual", "input": {}, "reasoning": "load guidance"}
        )
        assert result["status"] == "degraded"
        assert result["manual"] == ""
        assert result["manual_path"] == str(path)
        assert result["action"] == "manual"
        assert "error" in result
        assert "content" not in result
    finally:
        agent.stop(timeout=1.0)


def test_web_manual_child_rejects_nonempty_input_on_real_agent_bind(tmp_path):
    agent = _real_web_agent(tmp_path)
    try:
        manager = setup(agent, browser_port=_BrowserPort())
        result = manager.handle(
            {
                "action": "manual",
                "input": {"topic": "search"},
                "reasoning": "load guidance",
            }
        )
        assert result["status"] == "failed"
        assert result["error_code"] == "INVALID_ARGUMENT"
    finally:
        agent.stop(timeout=1.0)

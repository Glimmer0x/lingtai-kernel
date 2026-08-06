"""Tests for the opencode preset provider.

Covers: adapter registration, OpenCodeAdapter defaults (local serve endpoint,
Chat Completions wire, placeholder api_key), LLMService construction,
preset_connectivity entry, the preset template file shape, and preset
activation end-to-end.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _reload_registry():
    """Clear + re-register all adapters; restore on teardown."""
    from lingtai.llm._register import register_all_adapters
    from lingtai.llm.service import LLMService

    saved = dict(LLMService._adapter_registry)
    LLMService._adapter_registry.clear()
    try:
        register_all_adapters()
        return LLMService, saved
    except Exception:
        LLMService._adapter_registry.clear()
        LLMService._adapter_registry.update(saved)
        raise


def _restore_registry(saved: dict) -> None:
    from lingtai.llm.service import LLMService

    LLMService._adapter_registry.clear()
    LLMService._adapter_registry.update(saved)


class TestOpenCodeAdapter:
    def test_defaults_to_local_serve_endpoint(self):
        from lingtai.llm.opencode.adapter import (
            OpenCodeAdapter,
            _OPENCODE_SERVE_DEFAULT_URL,
        )

        adapter = OpenCodeAdapter()
        assert _OPENCODE_SERVE_DEFAULT_URL == "http://127.0.0.1:4050/v1"
        assert adapter.base_url == _OPENCODE_SERVE_DEFAULT_URL
        # Chat Completions wire by default — broadest-compat surface.
        assert adapter._should_use_responses() is False
        # Placeholder key satisfies the OpenAI SDK; opencode authenticates itself.
        assert adapter._client.api_key

    def test_respects_explicit_base_url(self):
        from lingtai.llm.opencode.adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter(base_url="http://127.0.0.1:4096/v1")
        assert adapter.base_url == "http://127.0.0.1:4096/v1"

    def test_prompt_cache_key_namespace(self):
        from lingtai.llm.opencode.adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        assert adapter._default_prompt_cache_key("anthropic/claude-sonnet-4-5") == (
            "lingtai-opencode:anthropic/claude-sonnet-4-5:v1"
        )

    def test_prompt_cache_key_disabled_by_default(self):
        from lingtai.llm.opencode.adapter import OpenCodeAdapter

        adapter = OpenCodeAdapter()
        assert adapter._resolve_prompt_cache_key("anthropic/claude-sonnet-4-5") is None


class TestRegistration:
    def test_opencode_registered_after_register_all(self):
        LLMService, saved = _reload_registry()
        try:
            assert "opencode" in LLMService._adapter_registry
        finally:
            _restore_registry(saved)

    def test_llm_service_builds_opencode_adapter(self):
        from lingtai.llm.opencode.adapter import OpenCodeAdapter

        LLMService, saved = _reload_registry()
        try:
            svc = LLMService("opencode", "anthropic/claude-sonnet-4-5")
            adapter = svc.get_adapter("opencode")
            assert isinstance(adapter, OpenCodeAdapter)
            assert adapter.base_url == "http://127.0.0.1:4050/v1"
            assert adapter._client.api_key  # placeholder
        finally:
            _restore_registry(saved)

    def test_llm_service_respects_manifest_base_url(self):
        LLMService, saved = _reload_registry()
        try:
            svc = LLMService(
                "opencode",
                "anthropic/claude-sonnet-4-5",
                base_url="http://127.0.0.1:4096/v1",
            )
            assert svc.get_adapter("opencode").base_url == "http://127.0.0.1:4096/v1"
        finally:
            _restore_registry(saved)


class TestPresetTemplate:
    def test_template_shape_mirrors_codex(self):
        template_path = ROOT / "presets" / "templates" / "opencode.json"
        data = json.loads(template_path.read_text(encoding="utf-8"))

        assert data["name"] == "opencode"
        llm = data["manifest"]["llm"]
        assert llm["provider"] == "opencode"
        assert llm["base_url"] == "http://127.0.0.1:4050/v1"
        assert isinstance(llm["model"], str) and "/" in llm["model"]
        assert llm["api_key"] is None
        assert llm["api_key_env"] == ""
        assert "thinking" not in llm
        # opencode vends no LingTai vision/web_search capability providers.
        caps = data["manifest"]["capabilities"]
        assert "vision" not in caps
        assert "web_search" not in caps
        assert "skills" in caps


def test_activate_opencode_preset(tmp_path):
    """Substituting the opencode preset into init.json works end-to-end."""
    from lingtai.agent import Agent

    plib = tmp_path / "presets"
    plib.mkdir()
    template = json.loads(
        (ROOT / "presets" / "templates" / "opencode.json").read_text("utf-8")
    )
    preset_path = str(plib / "opencode.json")
    (plib / "opencode.json").write_text(json.dumps(template))

    wd = tmp_path / "agent"
    wd.mkdir()
    init = {
        "manifest": {
            "agent_name": "alice",
            "language": "en",
            "preset": {
                "active": preset_path,
                "default": preset_path,
                "allowed": [preset_path],
            },
            "llm": {"provider": "deepseek", "model": "deepseek-v4-flash",
                    "api_key": None, "api_key_env": "DEEPSEEK_API_KEY"},
            "capabilities": {"file": {}},
            "soul": {"delay": 120},
            "max_turns": 50,
            "admin": {"karma": True},
            "streaming": False,
        },
        "principle": "p", "covenant": "c", "pad": "", "lingtai": "",
        "soul": "",
    }
    (wd / "init.json").write_text(json.dumps(init))

    class _Probe(Agent):
        def __init__(self, working_dir):
            self._working_dir = Path(working_dir)
            self._log_events = []
        def _log(self, event, **kw):
            self._log_events.append((event, kw))

    a = _Probe(wd)
    a._activate_preset(preset_path)

    data = json.loads((wd / "init.json").read_text(encoding="utf-8"))
    assert data["manifest"]["llm"]["provider"] == "opencode"
    assert data["manifest"]["llm"]["base_url"] == "http://127.0.0.1:4050/v1"
    assert data["manifest"]["llm"]["model"] == template["manifest"]["llm"]["model"]
    assert data["manifest"]["preset"]["active"] == preset_path


class TestPresetConnectivity:
    def test_opencode_has_default_url(self):
        from lingtai.kernel import preset_connectivity as pc

        assert pc._PROVIDER_DEFAULT_URLS["opencode"] == "http://127.0.0.1:4050"

    def test_check_connectivity_no_credential_check(self):
        """api_key_env "" skips the credential gate; the probe is a TCP check
        of the local serve port (ok only while a server is running)."""
        from lingtai.kernel import preset_connectivity as pc

        result = pc.check_connectivity("opencode", None, "")
        assert result["status"] in {"ok", "unreachable"}
        if result["status"] == "unreachable":
            assert result["error"]

    def test_check_connectivity_uses_manifest_base_url(self):
        from lingtai.kernel import preset_connectivity as pc

        result = pc.check_connectivity(
            "opencode", "http://127.0.0.1:4050/v1", ""
        )
        assert result["status"] in {"ok", "unreachable"}

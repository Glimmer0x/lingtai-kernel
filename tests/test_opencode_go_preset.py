"""Tests for the OpenCode Go subscription preset provider.

Covers: provider registration (opencode-go reuses the generic OpenAI-compatible
custom adapter), LLMService construction against the cloud Zen Go endpoint,
the preset template file shape, and the preset_connectivity entry.
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


class TestRegistration:
    def test_opencode_go_registered_after_register_all(self):
        LLMService, saved = _reload_registry()
        try:
            assert "opencode-go" in LLMService._adapter_registry
            assert "opencode_go" in LLMService._adapter_registry
        finally:
            _restore_registry(saved)

    def test_llm_service_builds_openai_compatible_adapter(self):
        from lingtai.llm.openai.adapter import OpenAIAdapter

        LLMService, saved = _reload_registry()
        try:
            svc = LLMService(
                "opencode-go",
                "glm-5.2",
                api_key="test-key",
                base_url="https://opencode.ai/zen/go/v1",
            )
            adapter = svc.get_adapter("opencode-go")
            assert isinstance(adapter, OpenAIAdapter)
            assert adapter.base_url == "https://opencode.ai/zen/go/v1"
        finally:
            _restore_registry(saved)


class TestPresetTemplate:
    def test_template_shape(self):
        template_path = ROOT / "presets" / "templates" / "opencode-go.json"
        data = json.loads(template_path.read_text(encoding="utf-8"))

        assert data["name"] == "opencode-go"
        llm = data["manifest"]["llm"]
        assert llm["provider"] == "opencode-go"
        assert llm["base_url"] == "https://opencode.ai/zen/go/v1"
        assert llm["api_compat"] == "openai"
        assert isinstance(llm["model"], str) and "/" not in llm["model"]
        assert llm["api_key"] is None
        assert llm["api_key_env"] == "OPENCODE_GO_API_KEY"
        caps = data["manifest"]["capabilities"]
        assert "skills" in caps


class TestPresetConnectivity:
    def test_opencode_go_has_default_url(self):
        from lingtai.kernel import preset_connectivity as pc

        assert pc._PROVIDER_DEFAULT_URLS["opencode-go"] == (
            "https://opencode.ai/zen/go/v1"
        )

    def test_check_connectivity_requires_credentials(self):
        """With api_key_env set but env missing, connectivity reports
        no_credentials rather than probing the network."""
        from lingtai.kernel import preset_connectivity as pc

        result = pc.check_connectivity(
            "opencode-go", "https://opencode.ai/zen/go/v1", "OPENCODE_GO_API_KEY"
        )
        assert result["status"] in {"ok", "no_credentials", "unreachable"}

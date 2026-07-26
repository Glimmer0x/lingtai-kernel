"""Focused contract regressions for the single public ``web`` capability."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from lingtai.tools.registry import BUILTIN_TOOLS, get_all_providers, normalize_capabilities
from lingtai.tools.web_search import setup
from lingtai.tools.web_search.settings import _bounded_error
from lingtai.tools.browser.port import TransportResponse


class _Agent:
    def __init__(self, root: Path) -> None:
        self._working_dir = root

    def add_tool(self, *args, **kwargs) -> None:
        self.tool_name = args[0]
        self.schema = kwargs["schema"]
        self.handler = kwargs["handler"]


class _Search:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str):
        self.calls.append(query)
        return [type("Result", (), {"title": "title", "url": "https://example.test/r", "snippet": "snippet"})()]


class _Port:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def resolve(self, hostname: str, *, timeout_s: float):
        return ["93.184.216.34"]

    def request(self, url: str, *, resolved, max_bytes: int, timeout_s: float):
        self.requests.append(url)
        return TransportResponse(200, {"content-type": "text/html"}, b"<p>page</p>", False, url)


def test_registry_has_one_web_surface_and_preserves_opaque_identity():
    assert BUILTIN_TOOLS["web"] == "lingtai.tools.web_search"
    assert "browser" not in BUILTIN_TOOLS
    assert "web_search" not in BUILTIN_TOOLS
    assert set(get_all_providers()) >= {"web"}
    assert "browser" not in get_all_providers()
    assert "web_search" not in get_all_providers()
    service = object()
    port = object()
    normalized = normalize_capabilities({"web_search": {"search_service": service, "browser_port": port}})
    assert normalized == {"web": {"search_service": service, "browser_port": port}}


def test_search_link_ref_browse_uses_same_agent_state(tmp_path):
    agent = _Agent(tmp_path)
    search = _Search()
    port = _Port()
    manager = setup(agent, search_service=search, browser_port=port)
    result = manager.handle({"action": "search", "parameters": {"query": "question"}})
    assert result["status"] == "ok"
    assert result["action"] == "search"
    assert result["count"] == 1
    assert result["results"][0]["link_ref"]
    assert not port.requests
    browsed = manager.handle({
        "action": "browse",
        "parameters": {
            "url": None,
            "link_ref": result["results"][0]["link_ref"],
            "cursor": None,
            "extract": None,
            "max_chars": None,
        },
    })
    assert browsed["status"] == "ok"
    assert browsed["action"] == "browse"
    assert len(port.requests) == 1
    assert search.calls == ["question"]


def test_settings_are_strict_reread_and_do_not_mutate_environment(tmp_path):
    agent = _Agent(tmp_path)
    search = _Search()
    manager = setup(agent, search_service=search, browser_port=_Port())
    settings = tmp_path / "settings" / "web.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"schema_version": 1, "search": {"engine": "not-admitted"}}))
    failure = manager.handle({"action": "search", "parameters": {"query": "x"}})
    assert failure["status"] == "failed"
    assert failure["current_setting"]["source"] == "settings_error"
    assert failure["current_setting"]["engine"] is None
    before = dict(os.environ)
    rejected = manager.handle({
        "action": "search",
        "parameters": {"query": "x", "engine": "duckduckgo"},
    })
    assert rejected["error_code"] == "INVALID_ARGUMENT"
    assert dict(os.environ) == before
    settings.write_text(json.dumps({"schema_version": 1, "search": {"engine": "duckduckgo"}}))
    success = manager.handle({"action": "search", "parameters": {"query": "x"}})
    assert success["status"] == "ok"
    assert success["current_setting"]["source"] == "settings/web.json"
    assert success["current_setting"]["settings_revision"]


def test_missing_and_operator_defaults_report_the_computed_source(tmp_path, monkeypatch):
    missing_env = "MISSING_WEB_SENTINEL"
    monkeypatch.delenv(missing_env, raising=False)
    built_agent = _Agent(tmp_path / "built")
    built = setup(built_agent, browser_port=_Port())
    built_result = built.handle({"action": "search", "parameters": {"query": ""}})
    assert built_result["current_setting"]["source"] == "built_in_default"
    assert built_result["current_setting"]["engine"] == "duckduckgo"

    operator_agent = _Agent(tmp_path / "operator")
    operator = setup(
        operator_agent,
        provider="gemini",
        api_key_env=missing_env,
        browser_port=_Port(),
    )
    result = operator.handle({"action": "search", "parameters": {"query": "question"}})
    assert result["error_code"] == "SEARCH_ENGINE_UNAVAILABLE"
    assert result["current_setting"]["source"] == "operator_default"
    statuses = result["current_setting"]["available_engines"]
    assert {item["api_key_env"] for item in statuses if item["status"] == "credential_missing"} == {"MISSING_WEB_SENTINEL"}
    assert "MISSING_WEB_SENTINEL_VALUE" not in json.dumps(result)


def test_settings_v1_rejects_boolean_and_float_schema_versions(tmp_path):
    agent = _Agent(tmp_path)
    manager = setup(agent, search_service=_Search(), browser_port=_Port())
    settings = tmp_path / "settings" / "web.json"
    settings.parent.mkdir()
    for version in (True, 1.0):
        settings.write_text(json.dumps({"schema_version": version, "search": {"engine": "duckduckgo"}}))
        result = manager.handle({"action": "search", "parameters": {"query": "question"}})
        assert result["error_code"] == "WEB_SETTINGS_INVALID"
        assert result["current_setting"]["engine"] is None


def test_invalid_settings_keep_manual_and_browse_usable(tmp_path):
    agent = _Agent(tmp_path)
    port = _Port()
    manager = setup(agent, search_service=_Search(), browser_port=port)
    settings = tmp_path / "settings" / "web.json"
    settings.parent.mkdir()
    settings.write_text("{not-json")
    manual = manager.handle({"action": "manual", "parameters": {}})
    assert manual["action"] == "manual"
    browsed = manager.handle({
        "action": "browse",
        "parameters": {
            "url": "https://example.test",
            "link_ref": None,
            "cursor": None,
            "extract": None,
            "max_chars": None,
        },
    })
    assert browsed["action"] == "browse"
    assert browsed["current_setting"]["source"] == "settings_error"


def test_oserror_diagnostics_never_echo_an_absolute_settings_path():
    absolute = "/private/secret-agent/settings/web.json"
    message = _bounded_error(PermissionError(13, "Permission denied", absolute))
    assert absolute not in message
    assert "settings/web.json" in message


def test_lazy_initialization_failure_updates_availability_truth(tmp_path, monkeypatch):
    secret = "DIRECT_SECRET_SENTINEL"

    def fail_factory(*args, **kwargs):
        raise RuntimeError("provider boot failed")

    monkeypatch.setattr("lingtai.services.websearch.create_search_service", fail_factory)
    manager = setup(
        _Agent(tmp_path),
        provider="gemini",
        api_key=secret,
        browser_port=_Port(),
    )
    result = manager.handle({"action": "search", "parameters": {"query": "question"}})
    assert result["error_code"] == "SEARCH_ENGINE_UNAVAILABLE"
    statuses = result["current_setting"]["available_engine_status"]
    assert statuses == {"gemini": "initialization_failed"}
    assert secret not in json.dumps(result)


def test_engine_selector_and_default_are_validated_at_composition(tmp_path):
    with pytest.raises(ValueError):
        setup(_Agent(tmp_path / "bad-name"), engines={"bad/name": {"provider": "duckduckgo"}}, browser_port=_Port())
    with pytest.raises(ValueError):
        setup(
            _Agent(tmp_path / "bad-default"),
            engines={"duckduckgo": {"provider": "duckduckgo"}},
            default_engine="gemini",
            browser_port=_Port(),
        )


def test_search_caps_an_unbounded_provider_iterable(tmp_path):
    class GeneratorSearch:
        def search(self, query):
            def results():
                index = 0
                while True:
                    yield {"title": str(index), "url": f"https://example.test/{index}", "snippet": "s"}
                    index += 1
            return results()

    manager = setup(_Agent(tmp_path), search_service=GeneratorSearch(), browser_port=_Port())
    result = manager.handle({"action": "search", "parameters": {"query": "question"}})
    assert result["status"] == "ok"
    assert result["count"] == 20
    assert len(result["results"]) == 20

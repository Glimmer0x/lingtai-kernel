"""Unified ``web`` capability: search, static browse, and its manual.

This retained package is the composition owner.  Search providers remain lazy
internal adapters, while the tested browser Core/Port stays in
``lingtai.tools.browser`` and is never registered as a separate public tool.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from itertools import islice
from typing import TYPE_CHECKING, Any, Mapping

from .._manual import load_installed_manual
from ..browser.core import BrowserEngine
from .settings import SettingsSnapshot, current_setting, read_settings, valid_engine_name

if TYPE_CHECKING:
    from lingtai.kernel.base_agent import BaseAgent
    from lingtai.services.websearch import SearchService
    from ..browser.port import BrowserPort

PROVIDERS = {
    "providers": ["duckduckgo", "minimax", "zhipu", "gemini", "anthropic", "openai"],
    "default": "duckduckgo",
    "fallback_on_inherit": "duckduckgo",
}

_ACTION_FIELDS = {
    "search": {"action", "query", "reasoning"},
    "browse": {"action", "url", "link_ref", "cursor", "extract", "max_chars", "reasoning"},
    "manual": {"action", "reasoning"},
}


def get_description(lang: str = "en") -> str:
    return (
        "Unified web capability. Use web(action='search', query='...') for current "
        "discovery, then web(action='browse', link_ref='...') for a known result. "
        "Use web(action='manual') for the procedure and settings guidance."
    )


def get_schema(lang: str = "en") -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["search", "browse", "manual"],
                "description": "Required operation: search, browse, or manual.",
            },
            "query": {"type": "string", "description": "Search query for action='search'."},
            "url": {"type": "string", "description": "Public HTTP(S) URL for action='browse'."},
            "link_ref": {"type": "string", "description": "Same-Agent result reference for action='browse'."},
            "cursor": {"type": "string", "description": "Same-Agent continuation cursor for action='browse'."},
            "extract": {"type": "string", "enum": ["article"], "default": "article"},
            "max_chars": {"type": "integer", "minimum": 1, "maximum": 100000, "default": 12000},
        },
        "required": ["action"],
        "additionalProperties": False,
    }


@dataclass(frozen=True, slots=True)
class _EngineSpec:
    name: str
    provider: str | None = None
    service: Any | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    model: str | None = None
    extra: Mapping[str, Any] = ()
    legacy_fallback_from: str | None = None


class WebManager:
    """One per-Agent dispatcher and search/browse state owner."""

    def __init__(
        self,
        agent: "BaseAgent",
        browser_port: "BrowserPort | None" = None,
        *,
        specs: Mapping[str, _EngineSpec] | None = None,
        default_engine: str | None = None,
        default_source: str = "built_in_default",
        search_service: Any | None = None,
        legacy_fallback_from: str | None = None,
    ) -> None:
        self._agent = agent
        if browser_port is None:
            from lingtai.adapters.browser_transport import VettedHttpTransport
            browser_port = VettedHttpTransport()
        self._engine = BrowserEngine(browser_port)
        if specs is None:
            specs = {"duckduckgo": _EngineSpec("duckduckgo", provider="duckduckgo", service=search_service)}
        self._specs = dict(specs)  # immutable spec values; service cache is local
        self._default_engine = default_engine or next(iter(self._specs), None)
        self._default_source = default_source
        self._legacy_fallback_from = legacy_fallback_from
        self._services: dict[str, Any] = {}
        self._service_errors: dict[str, str] = {}

    @property
    def browser_engine(self) -> BrowserEngine:
        return self._engine

    def _status(self, spec: _EngineSpec) -> str:
        if spec.service is not None or spec.provider == "duckduckgo":
            return "available"
        if spec.api_key:
            return "available"
        if spec.api_key_env and os.environ.get(spec.api_key_env):
            return "available"
        if spec.provider and spec.provider != "duckduckgo":
            return "credential_missing"
        return "unavailable"

    def _diagnostics(self, snapshot: SettingsSnapshot) -> dict[str, Any]:
        statuses = {
            name: (
                "initialization_failed"
                if name in self._service_errors
                else self._status(spec)
            )
            for name, spec in self._specs.items()
        }
        block = current_setting(snapshot, self._specs, statuses)
        if self._legacy_fallback_from:
            block["legacy_fallback_from"] = self._legacy_fallback_from[:64]
            block["legacy_fallback"] = "operator-config-only"
        return block

    def _resolve(self) -> tuple[str | None, SettingsSnapshot, dict[str, Any]]:
        snapshot = read_settings(
            self._agent, self._specs, self._default_engine, self._default_source
        )
        return snapshot.engine, snapshot, self._diagnostics(snapshot)

    def _failure(self, action: str, snapshot: SettingsSnapshot, diagnostic: dict[str, Any], code: str, message: str, **extra: Any) -> dict[str, Any]:
        result = {"status": "failed", "action": action, "error_code": code, "message": message, "current_setting": diagnostic}
        result.update(extra)
        return result

    def _service_for(self, name: str, spec: _EngineSpec) -> Any | None:
        if name in self._services:
            return self._services[name]
        if name in self._service_errors:
            return None
        if spec.service is not None:
            self._services[name] = spec.service
            return spec.service
        if self._status(spec) != "available":
            self._service_errors[name] = "credential_missing"
            return None
        try:
            # The provider factory is deliberately imported and called only on
            # the selected search path; manual/browse never construct one.
            from lingtai.services.websearch import create_search_service
            key = spec.api_key
            if spec.api_key_env:
                key = os.environ.get(spec.api_key_env)
            kwargs = dict(spec.extra) if isinstance(spec.extra, Mapping) else {}
            if spec.provider == "minimax" and "api_host" not in kwargs:
                from .._media_host import resolve_media_host
                kwargs["api_host"] = resolve_media_host(self._agent)
            if spec.provider == "zhipu" and "z_ai_mode" not in kwargs:
                from .._zhipu_mode import resolve_z_ai_mode
                kwargs["z_ai_mode"] = resolve_z_ai_mode(self._agent)
            service = create_search_service(spec.provider or name, api_key=key, model=spec.model, **kwargs)
            self._services[name] = service
            return service
        except Exception as exc:
            self._service_errors[name] = type(exc).__name__[:64]
            return None

    @staticmethod
    def _result_fields(item: Any) -> tuple[str, str, str]:
        if isinstance(item, Mapping):
            return (str(item.get("title", "")), str(item.get("url", item.get("link", ""))), str(item.get("snippet", item.get("content", ""))))
        return (str(getattr(item, "title", "")), str(getattr(item, "url", "")), str(getattr(item, "snippet", "")))

    def _search(self, args: dict[str, Any], snapshot: SettingsSnapshot, diagnostic: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query")
        if not isinstance(query, str) or not query.strip():
            return self._failure("search", snapshot, diagnostic, "INVALID_QUERY", "query must be a non-empty string")
        name = snapshot.engine
        if snapshot.error:
            return self._failure("search", snapshot, diagnostic, "WEB_SETTINGS_INVALID", "settings/web.json is invalid; no search engine was selected")
        if not name or name not in self._specs:
            return self._failure("search", snapshot, diagnostic, "SEARCH_ENGINE_UNAVAILABLE", "the selected search engine is unavailable")
        spec = self._specs[name]
        if self._status(spec) != "available":
            return self._failure("search", snapshot, diagnostic, "SEARCH_ENGINE_UNAVAILABLE", "the selected search engine is unavailable")
        service = self._service_for(name, spec)
        if service is None:
            # `_service_for` records a bounded internal failure marker. Rebuild
            # diagnostics so this same result does not contradict its error by
            # still advertising the engine as available.
            diagnostic = self._diagnostics(snapshot)
            return self._failure("search", snapshot, diagnostic, "SEARCH_ENGINE_UNAVAILABLE", "the selected search engine could not be initialized")
        try:
            raw_results = service.search(query)
            if raw_results is None:
                raw_results = []
            results: list[dict[str, str]] = []
            for item in islice(iter(raw_results), 20):
                title, url, snippet = self._result_fields(item)
                title, url, snippet = title[:512], url[:2048], snippet[:2000]
                if not url:
                    continue
                results.append({"title": title, "url": url, "snippet": snippet, "link_ref": self._engine.refs.add_link_ref(url)})
            return {
                "status": "ok", "action": "search", "query": query[:2000],
                "engine": name, "actual_engine": name, "results": results,
                "count": len(results), "current_setting": diagnostic,
            }
        except Exception:
            return self._failure("search", snapshot, diagnostic, "SEARCH_FAILED", "the selected search engine failed")

    def manual(self, snapshot: SettingsSnapshot, diagnostic: dict[str, Any]) -> dict[str, Any]:
        # This path is intentionally before _service_for and performs no provider
        # construction or search operation, even when settings are malformed.
        loaded = load_installed_manual(self._agent, "web")
        loaded.update({"action": "manual", "current_setting": diagnostic})
        return loaded

    def handle(self, args: dict[str, Any] | None) -> dict[str, Any]:
        raw = dict(args or {})
        action = raw.get("action")
        if action not in _ACTION_FIELDS:
            _, snapshot, diagnostic = self._resolve()
            return self._failure("unknown", snapshot, diagnostic, "ACTION_REQUIRED", "action must be one of search, browse, or manual")
        unknown = set(raw) - _ACTION_FIELDS[action]
        if unknown:
            _, snapshot, diagnostic = self._resolve()
            return self._failure(action, snapshot, diagnostic, "INVALID_ARGUMENT", "unsupported web argument")
        _, snapshot, diagnostic = self._resolve()
        if action == "manual":
            return self.manual(snapshot, diagnostic)
        if action == "search":
            return self._search(raw, snapshot, diagnostic)
        browse_args = dict(raw)
        try:
            result = self._engine.handle(browse_args)
        except Exception:
            result = {"status": "failed", "error_code": "BROWSE_FAILED", "message": "browse failed safely"}
        result["action"] = "browse"
        result["current_setting"] = diagnostic
        return result


# Retained import compatibility for callers that imported the old class.
WebSearchManager = WebManager


def _specs_from_kwargs(
    *, search_service: Any | None, provider: str | None, api_key: str | None,
    api_key_env: str | None, model: str | None, default_engine: str | None,
    engines: Mapping[str, Any] | None, kwargs: Mapping[str, Any],
) -> tuple[dict[str, _EngineSpec], str | None, str, str | None]:
    specs: dict[str, _EngineSpec] = {}
    legacy_fallback_from: str | None = None
    if default_engine is not None and not valid_engine_name(default_engine):
        raise ValueError("web default_engine must be a bounded engine name")
    if engines is not None:
        if not isinstance(engines, Mapping) or not engines:
            raise ValueError("web.engines must be a non-empty mapping")
        for name, raw in engines.items():
            if not valid_engine_name(name):
                raise ValueError("web engine names must use the bounded selector grammar")
            if isinstance(raw, Mapping):
                data = raw
                specs[name] = _EngineSpec(
                    name, provider=data.get("provider", name), service=data.get("search_service"),
                    api_key=data.get("api_key"), api_key_env=data.get("api_key_env"),
                    model=data.get("model"), extra={k: v for k, v in data.items() if k not in {"provider", "search_service", "api_key", "api_key_env", "model"}},
                )
            else:
                specs[name] = _EngineSpec(name, provider=name, service=raw)
        if default_engine is not None and default_engine not in specs:
            raise ValueError("web default_engine must name an admitted engine")
    elif search_service is not None or provider is not None or api_key is not None or api_key_env is not None or model is not None:
        # Retain the old operator-config fallback for an inherited/unknown
        # provider only. Explicit settings never enter this branch and therefore
        # can never be silently substituted.
        if provider and provider not in PROVIDERS["providers"]:
            legacy_fallback_from = provider
            specs["duckduckgo"] = _EngineSpec(
                "duckduckgo", provider="duckduckgo", service=search_service,
                legacy_fallback_from=provider,
            )
        else:
            name = default_engine or provider or "duckduckgo"
            if not valid_engine_name(name):
                raise ValueError("web engine names must use the bounded selector grammar")
            specs[name] = _EngineSpec(name, provider=provider or name, service=search_service, api_key=api_key, api_key_env=api_key_env, model=model, extra=kwargs)
    else:
        name = default_engine or "duckduckgo"
        if not valid_engine_name(name):
            raise ValueError("web engine names must use the bounded selector grammar")
        specs[name] = _EngineSpec(name, provider=name)
    if default_engine is not None and default_engine not in specs:
        raise ValueError("web default_engine must name an admitted engine")
    chosen = default_engine or (provider if provider in specs else next(iter(specs), None))
    source = "operator_default" if default_engine or provider or engines is not None or search_service is not None else "built_in_default"
    return specs, chosen, source, legacy_fallback_from


def setup(
    agent: "BaseAgent", search_service: Any | None = None, provider: str | None = None,
    api_key: str | None = None, api_key_env: str | None = None, model: str | None = None,
    default_engine: str | None = None, engines: Mapping[str, Any] | None = None,
    browser_port: "BrowserPort | None" = None, **kwargs: Any,
) -> WebManager:
    """Compose one unified ``web`` manager; provider construction is lazy."""
    if browser_port is None:
        from lingtai.adapters.browser_transport import VettedHttpTransport
        browser_port = VettedHttpTransport()
    specs, chosen, source, legacy_fallback_from = _specs_from_kwargs(
        search_service=search_service, provider=provider, api_key=api_key,
        api_key_env=api_key_env, model=model, default_engine=default_engine,
        engines=engines, kwargs=kwargs,
    )
    manager = WebManager(
        agent, browser_port, specs=specs, default_engine=chosen,
        default_source=source, legacy_fallback_from=legacy_fallback_from,
    )
    agent.add_tool(
        "web", schema=get_schema(), handler=manager.handle,
        description=get_description(), glossary_package=__package__,
    )
    return manager

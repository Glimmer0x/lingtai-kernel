---
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/ANATOMY.md
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/web_search/__init__.py
  - src/lingtai/tools/web_search/settings.py
  - src/lingtai/tools/web_search/manual/SKILL.md
  - src/lingtai/tools/browser/ANATOMY.md
  - src/lingtai/tools/browser/core.py
  - src/lingtai/tools/browser/port.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/services/websearch/ANATOMY.md
maintenance: |
  Keep this public web Anatomy and its Contract reciprocal, keep the parent
  link bidirectional, and keep the sole web-manual edge on both owner twins.
  Browser is an internal browse subcomponent, not another model-facing node.
  tool_family is generic optional infrastructure this package composes onto;
  web's own instance-bound diagnostics and dispatch wrapper remain here.
  Update this map with structural code changes and verify citations.
---
# Unified web capability Anatomy

The retained `web_search` package is the public `web` composition owner. It
combines lazy SearchService adapters with the internal browser Core while
exposing one model-facing handler and one per-Agent state boundary. Schema
composition and envelope dispatch delegate to the generic
`tool_family` infrastructure; this package retains ownership of
action implementations, settings, and diagnostics.

## Components

- `WebManager`, `setup()`, and the single `web` schema — builds a per-instance
  `ToolFamily` (`lingtai.tools.tool_family`) with `search`/`browse` handlers
  bound to instance state and a `manual` child from
  `tool_family.manual.build_manual_child`; `handle()` delegates envelope
  validation and dispatch to that `ToolFamily` and stamps
  `current_setting`/`action` onto envelope-level failures; lazy engine
  composition, settings diagnostics, and registration
  (`src/lingtai/tools/web_search/__init__.py:1-426`).
- `_EngineSpec`, `_specs_from_kwargs`, `_canonical_default_specs()` —
  immutable operator engine wiring. `_specs_from_kwargs` rejects a retired
  provider name (`minimax`, `zhipu` — `_RETIRED_PROVIDERS`) supplied via the
  flat `provider=`/`default_engine=` kwargs with `RetiredProviderError`, a
  composition-time exception, never a silent DuckDuckGo substitution;
  rejects a settings-gated engine name (`anthropic`, `gemini` —
  `_BACKEND_GATED_ENGINES`) supplied the same way with the distinct
  `SettingsOnlyProviderError` — Anthropic/Gemini are active canonical
  providers, never "retired". A retired provider named inside `engines={}`
  is rejected with `RetiredProviderError` the same way, while a genuinely
  unrecognized/inherited legacy provider name keeps the pre-existing
  `legacy_fallback_from`-tagged DuckDuckGo spec. The true no-config path
  (no kwargs at all) calls
  `_canonical_default_specs()`, which composes all four canonical providers
  using each provider's own standard `OPENAI_API_KEY`/`ANTHROPIC_API_KEY`/
  `GEMINI_API_KEY` environment variable as `_EngineSpec.api_key_env`
  (`_CANONICAL_API_KEY_ENV`) — never the current Agent's own live
  `agent.service` credentials (`src/lingtai/tools/web_search/__init__.py`).
- `WebManager._default_engine_now()` — the live, per-call built-in default
  resolver: canonical OpenAI Responses Web Search when genuinely available
  (present in the operator's engine set and `_status() == "available"`),
  else `duckduckgo` if composed, else `None` if the only remaining candidate
  is a settings-gated engine (never lands the built-in default on
  `anthropic`/`gemini`); only applies when no operator `default_engine`/
  `provider` was explicitly chosen (`_default_source == "built_in_default"`)
  (`src/lingtai/tools/web_search/__init__.py`).
- `_same_provider_identity()` — the truthful, exact-match canonical-provider
  identity check gating explicit Anthropic/Gemini opt-in against the current
  Agent's own live `agent.service.provider`; module-private to `web_search`
  (`src/lingtai/tools/web_search/__init__.py`) — only this capability's
  policy needs it, so it is not a cross-tool API.
- `WebManager._openai_duckduckgo_fallback()`/`_duckduckgo_fallback()` — the
  one automatic runtime fallback, triggered only by the exact
  `OpenAISearchError` subclass (never a bare `SearchProviderError` or
  `Exception`, so an `AnthropicSearchError`/`GeminiSearchError` and a
  manager/programming defect both fail normally instead of retrying):
  exactly one DuckDuckGo attempt, comment line plus bounded
  `openai_failure_class`/`duckduckgo_failure_class` provenance, no second
  retry, no fallback for any other engine. `WebManager._search`'s exception
  handler also recognizes the shared `SearchProviderError` base for any
  other typed provider failure and stamps a bounded `provider_failure_class`
  onto the `SEARCH_FAILED` result (`src/lingtai/tools/web_search/__init__.py`).
- `read_settings()` — bounded regular-file snapshot and strict v1 selector
  validation over the action-owned `settings/web.search.json`
  (`src/lingtai/tools/web_search/settings.py:49-182`).
- `BrowserEngine` — internal static browse use case, provenance, refs, cursors,
  SSRF policy, and typed failures (`src/lingtai/tools/browser/core.py:126-327`).
- `SearchService` adapters — provider implementations behind the internal
  service boundary (`src/lingtai/services/websearch/__init__.py:20-70`).
- `manual/SKILL.md` — sole installed `web-manual` route
  (`src/lingtai/tools/web_search/manual/SKILL.md:1-91`).

## Connections

`registry.py` maps public `web` to this package and maps legacy input
`web_search` one-way to `web`. `WebManager` calls only `SearchService` for
search and only `BrowserEngine` for browse; neither path crosses into the other
transport. Agent manual installation maps this retained package's `manual/` to
`capabilities/web/` and skips the retained browser manual.

## Composition

The parent [`src/lingtai/tools/ANATOMY.md`](../ANATOMY.md) owns capability
registry composition. The internal browse child
[`src/lingtai/tools/browser/ANATOMY.md`](../browser/ANATOMY.md) owns static-page
structure but has no public registration. The generic
[`src/lingtai/tools/tool_family/ANATOMY.md`](../tool_family/ANATOMY.md) owns
the reusable schema-composition/dispatch infrastructure this package builds
its `ToolFamily` instances from; it has no knowledge of web's own settings or
diagnostics. The shared
[`src/lingtai/tools/CONTRACT.md`](../CONTRACT.md) owns the future canonical public
call shape. The paired [`CONTRACT.md`](CONTRACT.md) specializes
that promise for web's actions, behavior, and evidence.

## State

Each manager owns immutable engine specs, a lazy per-engine service cache, one
browser engine, and its bounded ref/snapshot/cursor stores. Settings are read
from the Agent workdir on every call and never written by the capability.
Credentials stay in operator wiring or process configuration; no call mutates
environment state.

## Notes

`web_search` remains a physical implementation path and a read-only config
alias only. Provider-native wire names such as an API's `web_search` remain
unchanged. The manual's legacy scripts are procedure fallbacks, not public
handlers or additional catalog entries.

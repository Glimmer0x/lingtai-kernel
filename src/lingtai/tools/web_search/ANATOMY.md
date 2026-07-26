---
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/ANATOMY.md
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/web_search/__init__.py
  - src/lingtai/tools/web_search/settings.py
  - src/lingtai/tools/web_search/manual/SKILL.md
  - src/lingtai/tools/browser/ANATOMY.md
  - src/lingtai/tools/browser/core.py
  - src/lingtai/tools/browser/port.py
  - src/lingtai/services/websearch/ANATOMY.md
maintenance: |
  Keep this public web Anatomy and its Contract reciprocal, keep the parent
  link bidirectional, and keep the sole web-manual edge on both owner twins.
  Browser is an internal browse subcomponent, not another model-facing node.
  Update this map with structural code changes and verify citations.
---
# Unified web capability Anatomy

The retained `web_search` package is the public `web` composition owner. It
combines lazy SearchService adapters with the internal browser Core while
exposing one model-facing handler and one per-Agent state boundary.

## Components

- `WebManager`, `setup()`, and the single `web` schema — dispatch, lazy engine
  composition, settings diagnostics, and registration
  (`src/lingtai/tools/web_search/__init__.py:1-334`).
- `_EngineSpec` and `_specs_from_kwargs` — immutable operator engine wiring and
  legacy flat-config migration (`src/lingtai/tools/web_search/__init__.py:66-334`).
- `read_settings()` — bounded regular-file snapshot and strict v1 selector
  validation (`src/lingtai/tools/web_search/settings.py:49-180`).
- `BrowserEngine` — internal static browse use case, provenance, refs, cursors,
  SSRF policy, and typed failures (`src/lingtai/tools/browser/core.py:119-315`).
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
structure but has no public registration. The paired
[`CONTRACT.md`](CONTRACT.md) owns the unified interface promise.

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

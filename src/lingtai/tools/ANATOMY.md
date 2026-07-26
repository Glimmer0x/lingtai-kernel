---
related_files:
  - ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/ANATOMY.md
  - src/lingtai/tools/notification/ANATOMY.md
  - src/lingtai/tools/web_search/ANATOMY.md
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/_settings.py
  - src/lingtai/tools/browser/ANATOMY.md
  - src/lingtai/adapters/browser_transport.py
  - src/lingtai/tools/registry.py
  - src/lingtai/tools/glossary_validator.py
  - ENVIRONMENT_VARIABLES.md
maintenance: |
  Keep this registry Anatomy connected to its parent and the unified web owner.
  Browser is an internal browse child, not a second public capability. Update
  structural claims with code and keep reciprocal graph edges valid.
---
# src/lingtai/tools/

This package owns concrete built-in tools and the registry that composes them
onto an Agent. The kernel owns generic tool machinery; this layer owns public
capability names and lazy adapters.

## Components

- `CONTRACT.md` — future canonical model-facing tool call contract and explicit
  per-tool migration boundary.
- `registry.py` — intrinsic mapping, public `BUILTIN_TOOLS`, input aliases,
  defaults, normalization, setup, and check-caps metadata
  (`src/lingtai/tools/registry.py:40-359`).
- `web_search/` — public `web` composition owner for search, browse, settings,
  and manual (`src/lingtai/tools/web_search/ANATOMY.md`).
- `browser/` — internal static browse Core/Port used by `web`
  (`src/lingtai/tools/browser/ANATOMY.md`).
- `_manual.py` — bounded installed-manual loader
  (`src/lingtai/tools/_manual.py:1-29`).
- `_settings.py` — private Agent-owned placeholder-settings reader and
  secret-free current-setting diagnostic. It strictly validates the exact
  versioned no-op schema, rereads `settings/<bounded tool_name>.json` per call,
  and never supplies action, input, reasoning, or tool behavior.

## Connections

`Agent` calls registry setup. The public `web` row imports
`lingtai.tools.web_search` lazily. That owner imports the browser Core and
provider factory only at composition or action boundaries. The pinned browser
transport remains an outer adapter. `web_search` is accepted only as a
one-way configuration input alias and is never emitted as a public name.

## Composition

The parent [`src/lingtai/ANATOMY.md`](../ANATOMY.md) owns Agent composition.
The paired tools Contract owns the future canonical `action` / `input` /
`reasoning` public call shape and migration boundary. The web Contract specializes
that promise for the first real implementation; its Anatomy and the internal
browser Anatomy provide progressive disclosure. Other tool packages retain their
existing public shapes until explicitly migrated.

## State

No mutable state lives at package root. `WebManager` owns per-Agent engine
specs, lazy provider cache, BrowserEngine refs/snapshots/cursors, and settings
observations. No process-global environment mutation or cross-Agent state is
owned here.

## Notes

Physical legacy directories and provider-native wire strings remain for
compatibility. They must not become registry, schema, prompt, check-caps,
manual, or catalog entries under those old public names.

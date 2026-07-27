---
related_files:
  - ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/ANATOMY.md
  - src/lingtai/tools/notification/ANATOMY.md
  - src/lingtai/tools/web_search/ANATOMY.md
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/vision/ANATOMY.md
  - src/lingtai/tools/vision/CONTRACT.md
  - src/lingtai/tools/browser/ANATOMY.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/adapters/browser_transport.py
  - src/lingtai/tools/registry.py
  - src/lingtai/tools/glossary_validator.py
  - ENVIRONMENT_VARIABLES.md
maintenance: |
  Keep this registry Anatomy connected to its parent and the unified web owner.
  Browser is an internal browse child, not a second public capability. The
  generic tool_family package is optional composition infrastructure any
  future family migration may adopt, not a second registry. Update
  structural claims with code and keep reciprocal graph edges valid.
---
# src/lingtai/tools/

This package owns concrete built-in tools and the registry that composes them
onto an Agent. The kernel owns generic tool machinery; this layer owns public
capability names and lazy adapters.

## Components

- `CONTRACT.md` — the LingTai Tool Protocol (LTP): the future canonical
  model-facing tool call contract, the two-level family/action settings
  addressing and ownership rules, and the explicit per-tool migration boundary.
- `registry.py` — intrinsic mapping, public `BUILTIN_TOOLS`, input aliases,
  defaults, normalization, setup, and check-caps metadata
  (`src/lingtai/tools/registry.py:40-359`).
- `web_search/` — public `web` composition owner for search, browse, settings,
  and manual (`src/lingtai/tools/web_search/ANATOMY.md`).
- `vision/` — public `vision` composition owner: one action-separated family
  with canonical `analyze`/`manual` children over the existing direct
  provider routing (`src/lingtai/tools/vision/ANATOMY.md`).
- `browser/` — internal static browse Core/Port used by `web`
  (`src/lingtai/tools/browser/ANATOMY.md`).
- `tool_family/` — generic, optional ToolFamily/ChildTool schema-composition
  and dispatch infrastructure implementing the LTP v2 envelope, and the
  reusable ManualTool builder; `web` is its first real consumer and `vision`
  its second (`src/lingtai/tools/tool_family/ANATOMY.md`).
- `_manual.py` — bounded installed-manual loader
  (`src/lingtai/tools/_manual.py:1-29`).

## Connections

`Agent` calls registry setup. The public `web` row imports
`lingtai.tools.web_search` lazily. That owner imports the browser Core and
provider factory only at composition or action boundaries, and imports
`tool_family` to compose its schema and (optionally) dispatch. The public
`vision` row imports `lingtai.tools.vision`, which imports `tool_family` the
same way and reaches `lingtai.services.vision` only on the selected direct
route. The pinned browser transport remains an outer adapter. `web_search` is
accepted only as a one-way configuration input alias and is never emitted as a
public name.

## Composition

The parent [`src/lingtai/ANATOMY.md`](../ANATOMY.md) owns Agent composition.
The paired tools Contract owns LTP: the future canonical `action` / `input` /
`reasoning` / `summarize` public call shape, family/action settings ownership,
and the migration boundary. Read it there; this Anatomy does not restate those
promises. The web Contract specializes
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

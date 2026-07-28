---
related_files:
  - ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/ANATOMY.md
  - src/lingtai/tools/notification/ANATOMY.md
  - src/lingtai/tools/web_search/ANATOMY.md
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/file/ANATOMY.md
  - src/lingtai/tools/file/CONTRACT.md
  - src/lingtai/tools/vision/ANATOMY.md
  - src/lingtai/tools/vision/CONTRACT.md
  - src/lingtai/tools/soul/ANATOMY.md
  - src/lingtai/tools/soul/CONTRACT.md
  - src/lingtai/tools/browser/ANATOMY.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/system/ANATOMY.md
  - src/lingtai/tools/system/CONTRACT.md
  - src/lingtai/tools/context/ANATOMY.md
  - src/lingtai/tools/context/CONTRACT.md
  - src/lingtai/tools/knowledge/ANATOMY.md
  - src/lingtai/tools/knowledge/CONTRACT.md
  - src/lingtai/tools/pad/ANATOMY.md
  - src/lingtai/tools/pad/CONTRACT.md
  - src/lingtai/tools/lingtai/ANATOMY.md
  - src/lingtai/tools/lingtai/CONTRACT.md
  - src/lingtai/tools/avatar/ANATOMY.md
  - src/lingtai/tools/avatar/CONTRACT.md
  - src/lingtai/tools/bash/ANATOMY.md
  - src/lingtai/tools/bash/CONTRACT.md
  - src/lingtai/tools/bash/_tool_family.py
  - src/lingtai/adapters/browser_transport.py
  - src/lingtai/tools/registry.py
  - src/lingtai/tools/glossary_validator.py
  - ENVIRONMENT_VARIABLES.md
maintenance: |
  Keep this registry Anatomy connected to its parent and the unified web owner.
  Browser is an internal browse child, not a second public capability. The
  generic tool_family package is optional composition infrastructure any
  future family migration may adopt, not a second registry. context is its
  thirteenth consumer and the fifth migrated intrinsic. Update
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
  (`src/lingtai/tools/registry.py:39-344`).
- `web_search/` — public `web` composition owner for search, browse, settings,
  and manual (`src/lingtai/tools/web_search/ANATOMY.md`).
- `file/` — sole owner of the public `file` capability: the composed schema,
  the envelope dispatch, and all five operation implementations in
  `_read.py`/`_write.py`/`_edit.py`/`_glob.py`/`_grep.py`
  (`src/lingtai/tools/file/ANATOMY.md`).
- `vision/` — public `vision` composition owner: one action-separated family
  with canonical `analyze`/`manual` children over the existing direct
  provider routing (`src/lingtai/tools/vision/ANATOMY.md`).
- `browser/` — internal static browse Core/Port used by `web`
  (`src/lingtai/tools/browser/ANATOMY.md`).
- `tool_family/` — generic, optional ToolFamily/ChildTool schema-composition
  and dispatch infrastructure implementing the LTP v2 envelope, and the
  reusable ManualTool builder; `web` is its first real consumer, `mcp` its
  second, `knowledge` its third, `file` its fourth, `vision` its fifth,
  `avatar` its sixth, `soul` its seventh, `shell` its eighth, `skills` its
  ninth, `notification` its tenth, `system` its eleventh, `daemon` its
  twelfth, and `context` its thirteenth
  (`src/lingtai/tools/tool_family/ANATOMY.md`).
- `system/` — mandatory intrinsic owning the public `system` family: runtime,
  lifecycle, preset, and identity-naming actions behind one model-facing root
  (`src/lingtai/tools/system/ANATOMY.md`). It owns no public context-hygiene
  action — `summarize.py` stays here as the private engine `context` drives. Like `soul` and `notification` it is
  an intrinsic rather than a manager-owning capability, so it composes its
  schema from a module-level schema-only family and builds a dispatching one
  per `handle(agent, args)` call.
- `knowledge/` — private durable knowledge catalog, migrated to the LTP v2
  family envelope with the unchanged public actions `info`/`manual`
  (`src/lingtai/tools/knowledge/ANATOMY.md`).
- `soul/` — the `soul` intrinsic family: six action-separated children
  (`inquiry`, `flow`, `config`, `voice`, `dismiss`, `manual`) behind one
  model-facing root (`src/lingtai/tools/soul/ANATOMY.md`).
- `bash/` — public `shell` composition owner for run/poll/cancel/manual
  (`src/lingtai/tools/bash/ANATOMY.md`); the public model-facing schema is
  the ToolFamily-composed LTP v2 envelope (`bash/_tool_family.py`) and is the
  package's only schema/description pair, while `ShellManager` remains the
  unchanged execution engine behind an internal-only flat call shape.
- `notification/` — mandatory intrinsic owning the public `notification`
  family: `check`, three atomic dismiss actions, and `manual`
  (`src/lingtai/tools/notification/ANATOMY.md`). Its public model-facing schema
  is the ToolFamily-composed LTP v2 envelope; unlike the capability families it
  builds its dispatching family per call, because an intrinsic receives `agent`
  per call rather than owning a manager.
- `context/` — mandatory intrinsic owning the public `context` family: the
  agent's context lifecycle and hygiene — `molt`, `summarize`, `rebuild`, and
  `manual` — behind one root (`src/lingtai/tools/context/ANATOMY.md`). It
  replaces the former `psyche` root, which no longer exists at any
  model-visible or registry level: the two name actions moved to `system` and
  the public `system` summarize action moved in, split into the explicit
  record-only `summarize` and applying `rebuild`. Like `soul`/`notification` it
  builds its dispatching family per call, and it is the one family that
  *consumes* the kernel-injected `_tc_id` rather than merely dropping it.
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
public name. `soul` is a mandatory intrinsic (`INTRINSICS`, not
`BUILTIN_TOOLS`) and imports `tool_family` statically; because it is a module
rather than a per-Agent manager object, it composes its schema from a
module-level schema-only `ToolFamily` and builds an agent-bound one per
`handle(agent, args)` call. The public `shell` row imports `lingtai.tools.bash`
lazily; `bash/__init__.py` imports `tool_family` (via `bash/_tool_family.py`)
to compose the public action-separated schema (re-exported as the package's
canonical `get_schema`/`get_description`) and to translate `action`/`input`
calls into the internal flat shape `ShellManager.handle` consumes. `bash` is
the one-way legacy input alias for `shell` (`registry.py`) and is never
emitted as a public name or a second schema.

The public `file` row imports `lingtai.tools.file` lazily; that owner binds its
five operation modules once per manager and reaches the working tree only
through the injected `FileIOService`. Unlike `bash`/`web_search`, the file
migration kept no configuration aliases: `read`, `write`, `edit`, `glob`, and
`grep` are unknown capability names that fail loudly. Capability groups no
longer exist at all — `file` was `_GROUPS`' only entry, so the map,
`expand_groups`, and every consumer were deleted rather than left empty.

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

Retained physical legacy directories (`bash/`, `web_search/`) and
provider-native wire strings remain for compatibility. They must not become
registry, schema, prompt, check-caps, manual, or catalog entries under those old
public names. The five pre-migration file packages are not among them: they were
deleted outright into `file/`, so there is no legacy directory, contract,
glossary, or alias left for that surface.

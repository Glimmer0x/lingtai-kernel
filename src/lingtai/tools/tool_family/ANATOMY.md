---
related_files:
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/tool_family/__init__.py
  - src/lingtai/tools/tool_family/manual.py
  - src/lingtai/tools/web_search/ANATOMY.md
  - src/lingtai/tools/mcp/ANATOMY.md
  - src/lingtai/tools/knowledge/ANATOMY.md
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  Keep this component's ANATOMY.md and CONTRACT.md reciprocal and keep
  parent/child anatomy links bidirectional. Code is the structural source of
  truth: update this anatomy in the same change that moves files, symbols,
  connections, composition, or state. Verify every changed citation and run the
  architecture-document validation before merge.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
---
# src/lingtai/tools/tool_family/ Anatomy

This package owns the generic ToolFamily/ChildTool composition and dispatch
boilerplate a family MAY opt into when implementing the LingTai Tool Protocol
v2 shape defined in `../CONTRACT.md`. It standardizes the wire envelope
(`action`/`input`/`reasoning`/`summarize`) and the schema-composition and
dispatch-validation boilerplate that would otherwise be duplicated by every
hand-migrated family; it does not standardize implementations, handlers, or
result types (`../CONTRACT.md` "Implementation independence" is binding on
this package too — using it is optional, not mandatory).

## Components

- `ChildTool` — a frozen descriptor pairing one child's canonical name,
  `input_schema`, and `handler`; name doubles as the model `action` constant
  and dispatch key (`__init__.py:76-95`).
- `ToolFamily` — validates a fixed child registry (duplicate names and a
  `manual` reserved-name collision fail loudly at construction), composes a
  model-facing schema from each child's own `input_schema` plus a REQUIRED
  root `reasoning` string property (declared by the family schema itself, not
  left to Agent schema composition's property-only re-injection), and
  provides an optional `handle()` dispatcher: validates `action`, type-checks
  and strips root `summarize`, rejects unknown root fields, and rejects
  `input` keys outside the selected child's own declared schema properties
  before calling that child's handler with only its `input`
  (`__init__.py:98-281`). Two enforcement layers correlate `action` with
  `input`, generated purely from the child registry with no name/schema
  mapping table: (1) schema-level — a root `allOf` with one `if`/`then`
  condition per child, each `if` testing `action` via `const` against that
  child's own registry name, each `then` constraining `input` to that exact
  child's canonical schema; (2) dispatch-level — `handle()`'s own `input`-key
  check against the selected child's declared properties, which remains
  always-authoritative and fail-closed regardless of whether a given
  provider enforces `allOf`/`if`/`then` schema-side. Root-level `allOf`
  correlation was adopted after a live non-strict Codex Responses probe on
  2026-07-27 accepted a raw root `allOf`/`if`/`then` schema without error on
  the current route (see `CONTRACT.md` "Contract rules").
- `manual.py` — owns `MANUAL_INPUT_SCHEMA`, the single strict-empty `manual`
  input schema every family reuses, and `build_manual_child()`, which wraps
  `../_manual.py`'s
  `load_installed_manual()` into the ManualTool stable contract: strict empty
  input, and a handler whose actual return value (what `ToolFamily.handle()`
  dispatches back verbatim, once the returned `ChildTool` is registered
  directly and unwrapped in a family's own `ToolFamily`) is the canonical
  `content[0].text` (full body) / `structuredContent.manual_path` (host-local
  path) shape, with `status`/`error` loader facts preserved truthfully. The
  strict-empty input literal it registers is exported as `MANUAL_INPUT_SCHEMA`
  so a family composing a schema-only `ToolFamily` alongside its dispatching
  one reuses the same object instead of hand-copying it and drifting (`mcp`,
  `knowledge`, `file`, and `vision` all do; `manual.py:1-89`). Each
  `ChildTool` deep-copies `MANUAL_INPUT_SCHEMA` rather than sharing the
  literal, so one family's schema can never be mutated through another's.

## Connections

`web_search/__init__.py` is the first real consumer: `get_schema()` composes
the model-facing schema from a module-level schema-only `ToolFamily`, and each
`WebManager` instance builds its own per-instance `ToolFamily` with handlers
bound to that instance — search/browse close over instance state;
`manual.build_manual_child(agent, "web")`'s returned `ChildTool` is
registered *directly*, unwrapped, as the family's `manual` child, so
`ToolFamily.handle()` returns that child's canonical
`content`/`structuredContent` result verbatim for `action="manual"` (no
double wrap). `WebManager.handle()` calls `self._family.handle(args)` and,
strictly *after* that call returns, adapts a successfully dispatched manual
result back to Web's pre-migration public flat shape (`status`, `manual`,
`manual_path`, `action`, `current_setting`) via
`WebManager._adapt_manual_result` — this adaptation is Web's own
Host/presentation-layer responsibility, applied post-dispatch, never inside
a registered child. `handle()` also stamps its own `current_setting`
diagnostic onto any envelope-level failure result, since a generic
`ToolFamily` has no knowledge of a specific family's settings diagnostics.
This division follows `../CONTRACT.md` "Implementation independence": using
`ToolFamily.handle()` is `web`'s choice, not an inherited requirement.

`mcp/__init__.py` ([`../mcp/ANATOMY.md`](../mcp/ANATOMY.md)) is the second
consumer and the minimal shape of one: a two-child family (`info`, `manual`)
whose public tool name and action values are unchanged by the migration, where
both children take the canonical strict-empty `input`. It follows the same
division — the `manual` child from `build_manual_child(agent, "mcp")` is
registered directly and unwrapped, and `mcp`'s own flat `mcp_manual` public
shape is reconstructed post-dispatch by a Host-owned adapter. It also shows
what a family, not this package, must own when a pre-migration public error
envelope predates the generic dispatcher: `mcp` renders its exact
unknown-action envelope in its own `handle_mcp` *before* delegating, including
the missing-action empty-string default and unhashable `action` values that
`ToolFamily.handle`'s dict lookup would otherwise raise `TypeError` on. The
generic dispatcher's canonical error shape is never changed to accommodate a
consumer.

`knowledge/__init__.py` is the third real consumer
(`src/lingtai/tools/knowledge/ANATOMY.md`): one `_build_family(agent | None)`
is the single builder — `_FAMILY = _build_family(None)` backs `get_schema()`
with non-dispatching handlers, and `_build_family(agent)` binds the
`info`/`manual` operations named in `_CHILD_SPECS` per agent. Both children declare the canonical strict-empty
`input_schema`, so every `input` key is a cross-branch/unknown key rejected
before handler I/O. It registers its own `manual` child rather than
`build_manual_child`, because knowledge's public manual result is keyed
`knowledge_manual` — the child's canonical result is returned verbatim, so no
Host-layer flattening is needed. Its outer `handle()` normalizes only the
generic `ACTION_REQUIRED` envelope failure back to knowledge's exact
pre-migration unknown-action result.

## Composition

The parent [`../ANATOMY.md`](../ANATOMY.md) owns capability registry
composition and lists this package. The shared
[`../CONTRACT.md`](../CONTRACT.md) owns the LingTai Tool Protocol (LTP) the
schema this package composes must satisfy. The paired [`CONTRACT.md`](CONTRACT.md)
specializes that promise into this package's own Port/Adapters/rules. No
external MCP transport, endpoint, or registry is owned or touched here —
"MCP-compatible" describes only the `name`/`description`/`inputSchema`-shaped
internal descriptor convention `ChildTool` follows for clean internal
boundaries.

## State

No mutable state lives at package root. `ToolFamily` instances are immutable
after construction (a frozen child registry); `build_schema()` recomputes the
model-facing schema on every call rather than caching one at construction.
Any per-Agent state (engine specs, settings diagnostics, service caches)
belongs to the consuming family, as `WebManager` demonstrates.

## Notes

A fake `widget` family in `tests/test_tool_family_generic.py` and
`tests/test_tool_family_wire_parity.py` proves this package is generic, not
Web-specific. Building a family on `ToolFamily` is optional: a family may
hand-write an equivalent `handle()`/schema composition instead, exactly as
`web` did before adopting this package.

---
name: tool-family
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/tool_family/__init__.py
  - src/lingtai/tools/tool_family/manual.py
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/_manual.py
  - src/lingtai/tools/web_search/CONTRACT.md
  - src/lingtai/tools/web_search/__init__.py
  - src/lingtai/tools/skills/CONTRACT.md
  - src/lingtai/tools/skills/__init__.py
  - tests/test_tool_family_generic.py
  - tests/test_tool_family_wire_parity.py
  - tests/test_tool_family_manual_contract.py
maintenance: |
  This component contract is governed by the root CONTRACT.md. Keep
  related_files complete and repo-relative, including the paired ANATOMY.md,
  the ChildTool/ToolFamily Port, the web_search production Adapter, contract
  tests, and the ManualTool manual reference. Update this contract, the
  paired Anatomy, and affected families together when the envelope, schema
  composition, or dispatch boundary changes. Adding a family MAY adopt this
  package's ToolFamily/handle(); it MUST NOT be required to, per
  src/lingtai/tools/CONTRACT.md "Implementation independence".
---
# ToolFamily generic infrastructure

## Purpose

Generic, optional internal infrastructure implementing the LingTai Tool
Protocol v2 envelope (`../CONTRACT.md`) so a family need not hand-write its
own schema composition and dispatch-validation boilerplate. `ChildTool` +
`ToolFamily` compose one model-facing aggregate tool from a fixed registry of
internal, MCP-compatible-in-shape children; `manual.py` upgrades the existing
`#1058` `load_installed_manual()` return shape into the reusable ManualTool
stable contract. **Root acceptance requirement:** the ManualTool child's
actual, dispatched-to result (what `ToolFamily.handle()` returns verbatim for
`action="manual"`, per the no-double-wrap rule below) MUST carry the full
installed `SKILL.md` body at `content[0].text` and the model-visible
host-local path at `structuredContent.manual_path` — never only in an unused
presentational helper, and never only in a `_meta`-style side channel. A
family wanting a different public result shape (as `web` does — see
Adapters) owns that adaptation itself, in its own Host/presentation layer,
after dispatch. This package owns no transport, no external MCP surface, and
no second registry: it is a Host-process-internal composition helper only.

## Behavior

A `ToolFamily` is constructed from an ordered, fixed list of `ChildTool`
descriptors. Construction is where correctness is enforced: a duplicate child
name, or more than one child named the reserved `manual`, raises
`ToolFamilyError` immediately rather than registering silently. Once
constructed, `build_schema()` deterministically composes the model-facing
schema with two enforcement layers correlating `action` with `input`,
generated purely from the child registry (no name/schema mapping table),
both built from the same deep-copied canonical child schemas:

1. **Schema-level (`allOf`):** one `if`/`then` condition per child — each
   `if` tests root `action` via `const` against that child's own registry
   name (guarded by `required: ["action"]`); each `then` constrains root
   `input` to that exact child's canonical `input_schema`. Adopted after a
   live non-strict Codex Responses probe on 2026-07-27 accepted a raw root
   `allOf`/`if`/`then` schema without error on the current route (see
   `_scrub_responses_schema` in `../../llm/openai/adapter.py` for the
   corresponding wire-level change and its own scope note).
2. **`input.oneOf` disclosure:** the same per-child `input_schema`s, embedded
   verbatim under a `title`, retained under `input` for model discoverability
   of every action's exact shape in one place.

Both layers expose the envelope root `action`, `input`, required
`reasoning`, and optional `summarize` — exactly the four public fields;
`allOf` constrains them without adding a fifth field or duplicating `action`
inside `input`. Dispatch (`handle()`, below) remains the second,
always-authoritative enforcement layer regardless of whether a given
provider actually validates `allOf`/`if`/`then` schema-side before
invocation — it is additive, not a replacement.
`reasoning` is Host InvocationContext/audit metadata, so `build_schema()`
declares it itself (same property text Agent schema composition also
re-injects into every tool's `properties` uniformly, but that step never
touches `required` — a family must declare `reasoning` required itself to be
correct even before Agent composition runs). `build_schema()` always
advertises `summarize` to the model regardless of family; whether the kernel
actually honors it is a separate, per-family allowlist decision
(`kernel/tool_result_summary.py` `_LTP_V2_MIGRATED_FAMILIES`) that this
package does not own or enforce. Today only `web` is on that allowlist, so
`summarize` is meaningful for the one family that uses this infrastructure; a
family adopting `ToolFamily` without also joining the kernel allowlist would
advertise a model-visible `summarize` control that the kernel silently
ignores. Calling
`handle()` is optional: it validates the envelope (unknown `action`,
non-boolean `summarize`, unknown root fields, `input` keys outside the
selected child's own declared schema) before invoking exactly that child's
handler with only its own `input` mapping. A family MAY skip `handle()`
entirely and dispatch by hand — `web` uses it internally but still owns its
own outer `handle()` to stamp family-specific diagnostics onto envelope
failures, which this package has no knowledge of.

`build_manual_child` builds the reserved `manual` `ChildTool`: strict empty
input; its handler loads the existing `load_installed_manual()` shape
(`status`, `manual` full body, `manual_path`, optionally `error`) and maps it
to the canonical, actually-dispatched result: `content=[{"type": "text",
"text": <full body>}]` and `structuredContent={"manual_path": <path>}`, with
`status`/`error` preserved verbatim as truthful loader facts. This mapping is
not a second wrapper — it IS this child's own canonical result. A family
MUST register this `ChildTool` directly, unwrapped, in its own `ToolFamily`
(see Adapters): `ToolFamily.handle()` then returns it verbatim for
`action="manual"`, and any family-specific public shape adaptation happens
strictly after that call returns, in the family's own Host/presentation
layer — never inside this builder, its handler, or a wrapping `ChildTool`.

## Port

The provider-neutral boundary is `ChildTool.input_schema` (each child's own
canonical JSON Schema for `input`) and `ChildTool.handler`
(`Callable[[Mapping], dict]`, receiving only validated `input`). `ToolFamily`
composes these into one `FunctionSchema.parameters`-compatible dict via
`build_schema()` and, optionally, dispatches through `handle()`. Neither
method is a required interface a family must implement against — a
conforming family may satisfy the same wire shape without ever importing this
package, per `../CONTRACT.md` "Implementation independence".

## Adapters

`web_search/__init__.py` is the one production Adapter/consumer in this
candidate: `WebManager.__init__` builds a per-instance `ToolFamily` with
`search`/`browse` handlers bound to that instance, and registers
`manual.build_manual_child(agent, "web")`'s returned `ChildTool` *directly* —
unwrapped — as the family's `manual` child. `WebManager.handle()` calls
`self._family.handle(args)`, which therefore returns that child's canonical
`content`/`structuredContent` result verbatim for `action="manual"` (no
double wrap). Strictly *after* that call returns, `handle()` detects a
successfully dispatched manual result (`"content" in result`) and calls
`self._adapt_manual_result(result)` — a Host/presentation-only method that
flattens the canonical result to Web's pre-migration public shape (`status`,
`manual`, `manual_path`, `action`, `current_setting`), preserving the
`#1058` public result exactly. This adaptation belongs to `web`'s own
`handle()`, not to the generic child or any wrapper registered in place of
it. `WebManager.handle()` also stamps `current_setting` onto any
envelope-level failure result (search/browse/unknown-action) before
returning, unchanged from before.

`skills/__init__.py` (`../skills/CONTRACT.md`) is the second production
Adapter/consumer. One `_build_family(agent, paths)` builder is its single
canonical child registry, registering an `info` child and
`manual.build_manual_child(agent, "skills")` directly — unwrapped; both
`get_schema()` (through an import-time `agent=None` instance whose handlers are
unreachable) and `setup()` obtain their `ToolFamily` from that one builder, so
the composed schema advertises exactly the child `input_schema`s dispatch
registers. Its `handle_skills` wrapper adapts only a successfully
dispatched manual result (`"content" in result`) to that capability's public
`skills_manual`/`library_manual`/`manual_path` shape, post-dispatch. Unlike
`web`, it returns this package's canonical envelope-failure result verbatim,
having no family-specific diagnostic block to stamp on; both of its children
declare the canonical strict-empty `input_schema`, so `handle()`'s
allowed-key check rejects every `input` key on either action. The two
consumers share nothing but this package, as
`../CONTRACT.md` "Implementation independence" requires. No other built-in
family is migrated in this candidate; each remains fully independent of this
package until its own scoped migration.

## Contract rules

- A `ToolFamily`'s child registry MUST be validated at construction: duplicate
  child names and more than one child named the reserved `manual` MUST raise
  `ToolFamilyError`, not register silently or resolve by precedence.
- `build_schema()` MUST embed each child's own `input_schema` verbatim (no
  copy-and-reshape) under a `oneOf` branch pairing it with that child's
  `title`. It MUST declare a root `reasoning` string property and include
  `reasoning` in the root `required` list — `reasoning` is Host
  InvocationContext/audit metadata, not left to Agent schema composition's
  property-only re-injection, which never touches `required`.
- `build_schema()` MUST also compose a root `allOf` with exactly one
  `if`/`then` condition per registered child, generated purely from the
  child registry: `if.properties.action.const` MUST equal that child's own
  registry name, `if.required` MUST be `["action"]`, and
  `then.properties.input` MUST be that exact child's own canonical
  `input_schema` (the same deep-copied schema the `oneOf` branch embeds, not
  a separately-maintained copy). This correlates `action` with `input` at
  the schema level without adding a fifth public root field or duplicating
  `action` inside `input`.
- `handle()`, when used, MUST validate `action` against the registry, type-
  check and strip root `summarize` before any child handler runs, reject
  unknown root fields, and reject `input` keys outside the selected child's
  own declared schema `properties` — schema conformance alone is not the
  sole enforcement boundary; dispatch remains always-authoritative and
  fail-closed regardless of whether a given provider validates the root
  `allOf`/`if`/`then` schema-side (`../CONTRACT.md` "Dispatch and actions").
- An `action` value that is unhashable (invalid JSON can make it `[]` or
  `{}`) MUST return the same typed `ACTION_REQUIRED` envelope failure as any
  other unknown action, never raise. Membership-testing an unhashable key
  against the child registry raises `TypeError`; `handle()` MUST treat that
  as matching no child, mirroring the hand-written routers this dispatcher
  replaces (`kernel/tool_dispatch.py`, issue #513).
- A child handler MUST receive only its own validated `input` mapping — never
  `action`, `reasoning`, `_reasoning`, or `summarize`.
- `handle()`'s dispatch result IS the child's own raw/canonical result;
  `ToolFamily` MUST NOT wrap it a second time.
- This package MUST NOT require inheritance from a shared base/port class, a
  shared handler, common request/result types, or a universal domain result
  shape from any consumer family, matching `../CONTRACT.md` "Implementation
  independence" verbatim.
- `manual.build_manual_child`'s child MUST use the reserved name `manual`, a
  strict empty `input_schema`, and its handler's actual return value — what
  `ToolFamily.handle()` dispatches back verbatim — MUST be the canonical
  `content[0].text` (full body) / `structuredContent.manual_path` (host-local
  path) shape, never the pre-mapping flat `load_installed_manual()` dict.
  `status`/`error` loader facts MUST be preserved truthfully alongside those
  two fields, not dropped or double-wrapped.
- A family MUST register `build_manual_child`'s returned `ChildTool` directly
  in its own `ToolFamily` — never wrapped in another handler that adapts or
  reshapes the result before `ToolFamily.handle()` returns it. Any
  family-specific public-shape adaptation (as `web` needs) MUST happen
  strictly after the family's own outer dispatch call returns, in that
  family's own Host/presentation layer, per the no-double-wrap rule above.
- This package owns no external MCP mounting, registry, adapter, schema, or
  test; it MUST NOT be extended to add one.

## Contract tests

`tests/test_tool_family_generic.py` proves the infrastructure is generic using
a fake `widget` family unrelated to `web`: deterministic registration order,
duplicate-name and reserved-`manual`-collision failures, `oneOf` schema
composition with root `reasoning` REQUIRED and no unconstrained generic
`input` object, dispatch selecting the correct child and passing only its
`input`, unknown-action/non-boolean-summarize/unknown-root-field/cross-branch-
key rejection, no double result wrapping, and two dedicated proofs that
`reasoning`/`summarize` never reach a child handler and never appear in any
child's own canonical `input_schema`. It also proves the root `allOf`
correlation directly: every condition's `action` const matches the child
registry name, `then.input` exactly matches that child's own canonical
schema, a minimal local `if`/`then` structural evaluator (no JSON Schema
dependency added) shows the schema itself rejects a mismatched
`action`/`input` pairing, `handle()` remains authoritative and fail-closed
regardless, and both the `allOf` conditions and the `oneOf` branches are
mutation-isolated from each other and from a child's own canonical schema.
`tests/test_tool_family_wire_parity.py`
proves the composed schema (including required `reasoning`) survives both
Chat Completions and Responses wires (including a real Agent
startup for `web`) at the existing OpenAI adapter seam with zero adapter code
changes. `tests/test_tool_family_manual_contract.py` invokes the actual
generic manual child handler (not an unused presentational helper) and
proves the ManualTool reserved name, strict empty input, the canonical
`content[0].text`/`structuredContent.manual_path` return shape,
missing-manual degraded case, and the reserved-name collision. It also
proves the registration/adaptation ownership boundary directly:
`manager._family.handle(...)` — the real `ToolFamily` `web` registers its
`manual` child in, unwrapped — returns the canonical
`content`/`structuredContent` result verbatim for a manual call, with none of
Web's legacy flat fields; `manager.handle(...)` on the identical envelope
returns Web's exact pre-migration public flat shape (`status`, `manual`,
`manual_path`, `action`, `current_setting`) with no canonical fields, for
both the success and missing-manual/degraded cases, via
`WebManager._adapt_manual_result`'s post-dispatch adaptation.
`tests/test_tool_family_web_migration_parity.py` snapshots `web`'s
pre-migration schema and proves the now-generated schema is field-equivalent
except the three authorized differences (`anyOf` → `oneOf`, required
`reasoning`, and the added root `allOf`), and separately proves `web`'s own
`allOf` correlates every real action's `const` with its exact branch schema.
`tests/test_tool_family_generic_summarize_executor.py` proves the raw-logged-
before-summary executor mechanism needs no family-specific kernel wiring,
using the fake `widget` family. `web`'s own existing suite
(`tests/test_unified_web_capability.py`,
`tests/test_web_ltp_v2_summarize_executor.py`, `tests/test_wire_tool_description.py`
— the last of which now also proves root `allOf` correlation survives
identically on both Chat Completions and Responses wires)
remains this migration's Web-specific evidence per `../web_search/CONTRACT.md`.

## Maintenance

Keep this Contract and `ANATOMY.md` reciprocal. Update the Port
(`ChildTool`/`ToolFamily`), the `web_search` Adapter, and contract tests
together when the envelope or dispatch boundary changes. Do not add a second
family here merely because it exists — a family joins this contract's
Adapters list only when it actually migrates onto this package, per
`../CONTRACT.md` "Migration is one family at a time."

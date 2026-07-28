---
related_files:
  - src/lingtai/tools/substrate/CONTRACT.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/substrate/__init__.py
  - src/lingtai/tools/substrate/glossary-en.md
  - src/lingtai/tools/substrate/glossary-zh.md
  - src/lingtai/tools/substrate/glossary-wen.md
  - src/lingtai/intrinsic_skills/substrate-manual/SKILL.md
maintenance: |
  Keep paths real, repo-relative, duplicate-free, and reciprocal with the paired
  Contract and parent/neighbor anatomies. Code is the structural source of
  truth: update this graph when symbols, connections, state ownership, or
  composition move.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
---
# tools/substrate

Mandatory LTP v2 family that is the one public root for the four durable
domains. Every action is a read-only manual loader; the package owns no domain
state, no catalog, and no composer.

## Components

- `DOMAIN_MANUALS` — the one fixed registry mapping each domain action to the
  installed manual it loads (`src/lingtai/tools/substrate/__init__.py:63-68`).
- `ACTION_ORDER` — the exact public inventory `pad | lingtai | knowledge |
  skills | manual`, derived from that registry
  (`src/lingtai/tools/substrate/__init__.py:72`).
- `_ROUTER_MANUAL` — the routing-table manual name loaded by the reserved
  `manual` child (`src/lingtai/tools/substrate/__init__.py:76`).
- `_build_children` — builds all five children from the shared
  `build_manual_child` loader with one strict-empty input schema
  (`src/lingtai/tools/substrate/__init__.py:81-107`).
- `_FAMILY`, `get_schema`, `get_description` — schema-only family plus the
  model-facing routing prose (`src/lingtai/tools/substrate/__init__.py:110-152`).
- `_adapt_manual_result` — the one post-dispatch Host adapter producing the flat
  `{status, manual, manual_path}` shape
  (`src/lingtai/tools/substrate/__init__.py:155-172`).
- `handle` — drops intrinsic `_tc_id`, dispatches through the generic family,
  and renders substrate-shaped unknown-action errors
  (`src/lingtai/tools/substrate/__init__.py:175-196`).

## Connections

- `tools/registry.py` wires this package into `INTRINSICS` as the mandatory
  public `substrate` root; `kernel/tool_result_summary.py` carries it in
  `_LTP_V2_MIGRATED_FAMILIES` and `tools/daemon` in `EMANATION_BLACKLIST`.
- Dispatch and schema composition flow through
  [`tool_family`](../tool_family/ANATOMY.md); every child's loader is
  `tool_family/manual.py::build_manual_child`, which reads
  `.library/intrinsic/capabilities/<name>/SKILL.md` via `tools/_manual.py`.
- The four domain manuals are installed by
  `Agent._install_intrinsic_manuals`: `pad-manual` and `lingtai-manual` from
  `intrinsic_skills/`, `knowledge` and `skills` from those packages' own
  `manual/` directories. The routing table ships as
  `intrinsic_skills/substrate-manual/`.
- No edge runs the other way: nothing in this package is imported by the domain
  packages, `Agent._reload_prompt_sections`, or the catalog composers.

## Composition

Parent: [`tools/ANATOMY.md`](../ANATOMY.md). Paired interface promise:
[`CONTRACT.md`](CONTRACT.md). Structurally relevant siblings are the four domain
owners — [`pad`](../pad/ANATOMY.md), [`lingtai`](../lingtai/ANATOMY.md),
[`knowledge`](../knowledge/ANATOMY.md), [`skills`](../skills/ANATOMY.md) — which
retain their private composers, catalogs, and lifecycle; this package routes to
their manuals and holds no reference to their internals.

## State

None. The package writes no persistent state and manages no ephemeral state: it
reads installed manual files and returns their bodies. Prompt sections, catalogs,
`system/pad.md`, `system/pad_append.json`, `system/lingtai.md`, `knowledge/`, and
`.library/` are all owned elsewhere and are untouched here.

## Notes

The kernel-owned prompt section also named `substrate` is a different concept in
a disjoint namespace; see the paired Contract. Because every child shares one
loader and one strict-empty schema, a side effect cannot be added to a single
action without changing `_build_children` for all of them — the read-only
promise is structural, not conventional.

---
related_files:
  - src/lingtai/tools/lingtai/CONTRACT.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/psyche/ANATOMY.md
  - src/lingtai/tools/lingtai/__init__.py
  - src/lingtai/tools/lingtai/_lingtai.py
  - src/lingtai/tools/lingtai/glossary-en.md
  - src/lingtai/tools/lingtai/glossary-zh.md
  - src/lingtai/tools/lingtai/glossary-wen.md
  - src/lingtai/intrinsic_skills/lingtai-manual/SKILL.md
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files,
  including the paired CONTRACT.md and the lingtai-manual both owner twins
  carry. Keep this component's ANATOMY.md and CONTRACT.md reciprocal and keep
  parent/child anatomy links bidirectional. Code is the structural source of
  truth: update this anatomy in the same change that moves files, symbols,
  connections, composition, or state. Verify every changed citation and run the
  architecture-document validation before merge.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
---
# tools/lingtai

The agent's 灵台 (character): the self-authored identity held in
`system/lingtai.md` and rendered into the protected `character` section of the
system prompt. One mandatory intrinsic owning one model-visible LTP v2 family
root, split out of `psyche` because the identity is a concept parallel to
`knowledge` and `skills` rather than a leaf of the context lifecycle. The Python
package is `lingtai.tools.lingtai` — the tool family, not the top-level
`lingtai` package.

## Components

- `__init__.py` — package surface and the LTP v2 family composition.
  - The two canonical child `input` schemas, one per action
    (`src/lingtai/tools/lingtai/__init__.py:59-76`) — each action's own strict,
    closed object, declared exactly once.
  - `_CHILD_SPECS` / `ACTION_ORDER`
    (`src/lingtai/tools/lingtai/__init__.py:89-95`) — the single registry of
    (name, schema, handler) plus the derived public action order. Because the
    model-facing schema and the dispatch allow-list are generated from this one
    source, a child can never be schema-advertised but dispatch-rejected.
  - `_DROPPED_ENVELOPE_KEYS` / `_strip_nulls` / `_build_children`
    (`src/lingtai/tools/lingtai/__init__.py:101-137`) — the transport metadata
    this family drops at its own Host boundary, the null→absent normalizer kept
    as the one normalization seam, and the builder that binds all three
    children (the reserved `manual` from `build_manual_child` appended last).
  - `_FAMILY` (`src/lingtai/tools/lingtai/__init__.py:140`) — the module-level
    schema-only `ToolFamily`; constructing it at import time is also the
    registry's duplicate/reserved-name collision check.
  - `get_description` / `get_schema`
    (`src/lingtai/tools/lingtai/__init__.py:162-179`) — tool registration;
    `get_schema` returns the `ToolFamily`-composed closed envelope with this
    family's own action-routing prose substituted for the generic placeholder.
  - `_adapt_manual_result`
    (`src/lingtai/tools/lingtai/__init__.py:185-203`) — Host-owned,
    post-dispatch flattening of the reserved `manual` child's canonical result
    back to the flat intrinsic manual shape.
  - `handle()` (`src/lingtai/tools/lingtai/__init__.py:206-243`) — the family
    root: drops `_tc_id`, builds the agent-bound `ToolFamily` per call, and
    normalizes the generic unknown-action envelope to this family's own error.
  - `boot()` (`src/lingtai/tools/lingtai/__init__.py:246-257`) — boot-time
    hook: loads the identity and registers the post-molt reload callback.

- `_lingtai.py` — identity management, moved verbatim from
  `psyche/_lingtai.py`.
  - `_lingtai_update()` (`src/lingtai/tools/lingtai/_lingtai.py:11-22`) — write
    content to `system/lingtai.md`, then auto-load.
  - `_lingtai_load()` (`src/lingtai/tools/lingtai/_lingtai.py:25-55`) — the
    single canonical writer of the protected `character` prompt section,
    composed from `system/lingtai.md` alone. An empty or missing file deletes
    the section. The file is either materialized from nonempty configured
    content (inline or resolved from `lingtai_file`) or preserved for
    self-evolve mode. Distinct from `covenant` (operator contract, owned by
    `Agent._reload_prompt_sections`) and from the mechanical `identity` section
    (written by BaseAgent).

## Connections

- **Inbound:** `handle()` is called by the tool dispatcher (via
  `base_agent._dispatch_tool`). `boot()` is called during agent construction by
  the generic intrinsic-boot loop in
  `src/lingtai/kernel/base_agent/__init__.py:788-796`.
- **Inbound (cross-module):** `_lingtai_load` is imported by
  `src/lingtai/agent.py:1728-1729` (`_reload_prompt_sections`) as the single
  canonical composer of the `character` prompt section, immediately after the
  configured identity seed is materialized; `boot` is re-run by
  `src/lingtai/agent.py:1561-1567` after a refresh so the post-molt hook is
  re-registered on the cleared hook list.
- **Registration:** `src/lingtai/tools/registry.py:50-66` wires `lingtai` into
  `INTRINSICS` (imported as `lingtai_tool` so the family and the top-level
  package cannot be confused at a callsite);
  `src/lingtai/kernel/tool_result_summary.py` lists it in
  `_LTP_V2_MIGRATED_FAMILIES`; `src/lingtai/tools/daemon/__init__.py` lists it
  in `EMANATION_BLACKLIST`.
- **Outbound:** `..tool_family` for schema composition and dispatch,
  `..tool_family.manual` for the reserved child, and `.._manual` for the
  installed manual loader.
- **Data flow:** all state is filesystem state under the agent working
  directory — `system/lingtai.md`. The prompt `character` section is derived,
  written through `agent._prompt_manager` with `protected=True`.

## Composition

The parent [`src/lingtai/tools/ANATOMY.md`](../ANATOMY.md) owns the registry
and the tool package map. The paired [`CONTRACT.md`](CONTRACT.md) owns this
family's interface promises — the closed envelope, the destructive-rewrite
semantics, and the two identity modes — and this anatomy does not restate them.
The generic composition infrastructure is
[`../tool_family/ANATOMY.md`](../tool_family/ANATOMY.md).
[`../psyche/ANATOMY.md`](../psyche/ANATOMY.md) is the structurally relevant
sibling: this family's two actions were psyche leaves before the split, and
psyche retains the molt that reloads the `character` section afterwards.
[`lingtai-manual`](../../intrinsic_skills/lingtai-manual/SKILL.md) teaches the
capability.

## State

Persistent: `system/lingtai.md` under `agent._working_dir`. Ephemeral: none
owned at module level — the family is rebuilt per `handle()` call, and the
module-level `_FAMILY` is schema-only and never dispatches.

## Notes

The identity survives a molt: the durable file is untouched by the shed, and the
post-molt hook this package registers reloads it into the fresh session's
prompt. In forced identity mode a nonempty configured value is re-materialized
into the same file on every reconstruction, overwriting an agent-authored
update from the previous cycle — that authority is unchanged by the split and
is described in the paired Contract. The pre-split `psyche(action="lingtai_*")`
call shape is not a compatibility alias — it is simply an unknown psyche action
and fails loudly.

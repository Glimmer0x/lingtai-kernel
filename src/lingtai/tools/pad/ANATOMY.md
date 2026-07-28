---
related_files:
  - src/lingtai/tools/pad/CONTRACT.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/psyche/ANATOMY.md
  - src/lingtai/tools/pad/__init__.py
  - src/lingtai/tools/pad/_pad.py
  - src/lingtai/tools/pad/glossary-en.md
  - src/lingtai/tools/pad/glossary-zh.md
  - src/lingtai/tools/pad/glossary-wen.md
  - src/lingtai/intrinsic_skills/pad-manual/SKILL.md
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files,
  including the paired CONTRACT.md and the pad-manual both owner twins carry.
  Keep this component's ANATOMY.md and CONTRACT.md reciprocal and keep
  parent/child anatomy links bidirectional. Code is the structural source of
  truth: update this anatomy in the same change that moves files, symbols,
  connections, composition, or state. Verify every changed citation and run the
  architecture-document validation before merge.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
---
# tools/pad

The agent's sketchboard in its own system prompt: the `system/pad.md` body plus
the pinned read-only reference files it re-reads on every load. One mandatory
intrinsic owning one model-visible LTP v2 family root, split out of `psyche`
because the pad is a concept parallel to `knowledge` and `skills` rather than a
leaf of the context lifecycle.

## Components

- `__init__.py` — package surface and the LTP v2 family composition.
  - The three canonical child `input` schemas, one per action
    (`src/lingtai/tools/pad/__init__.py:60-105`) — each action's own strict,
    closed object, declared exactly once.
  - `_CHILD_SPECS` / `ACTION_ORDER`
    (`src/lingtai/tools/pad/__init__.py:109-116`) — the single registry of
    (name, schema, handler) plus the derived public action order. Because the
    model-facing schema and the dispatch allow-list are generated from this one
    source, a child can never be schema-advertised but dispatch-rejected.
  - `_DROPPED_ENVELOPE_KEYS` / `_strip_nulls` / `_build_children`
    (`src/lingtai/tools/pad/__init__.py:122-161`) — the transport metadata pad
    drops at its own Host boundary, the null→absent normalizer that preserves
    the handlers' absent-vs-null behavior, and the builder that binds all four
    children (the reserved `manual` from `build_manual_child` appended last).
  - `_FAMILY` (`src/lingtai/tools/pad/__init__.py:164`) — the module-level
    schema-only `ToolFamily`; constructing it at import time is also the
    registry's duplicate/reserved-name collision check.
  - `get_description` / `get_schema`
    (`src/lingtai/tools/pad/__init__.py:186-203`) — tool registration;
    `get_schema` returns the `ToolFamily`-composed closed envelope with pad's
    own action-routing prose substituted for the generic placeholder.
  - `_adapt_manual_result` (`src/lingtai/tools/pad/__init__.py:209-227`) —
    Host-owned, post-dispatch flattening of the reserved `manual` child's
    canonical result back to the flat intrinsic manual shape.
  - `handle()` (`src/lingtai/tools/pad/__init__.py:230-267`) — the family root:
    drops `_tc_id`, builds the agent-bound `ToolFamily` per call, and
    normalizes the generic unknown-action envelope to pad's own error.
  - `boot()` (`src/lingtai/tools/pad/__init__.py:270-281`) — boot-time hook:
    loads the pad and registers the post-molt reload callback.

- `_pad.py` — pad management, moved verbatim from `psyche/_pad.py`.
  - Append-file management: `_APPEND_LIST_PATH` / `_APPEND_TOKEN_LIMIT`
    constants (`src/lingtai/tools/pad/_pad.py:13-14`), `_append_list_file`
    (`src/lingtai/tools/pad/_pad.py:17`), `_load_append_list`
    (`src/lingtai/tools/pad/_pad.py:21-32`), `_save_append_list`
    (`src/lingtai/tools/pad/_pad.py:35-39`), `_resolve_path`
    (`src/lingtai/tools/pad/_pad.py:42-45`), `_read_append_content`
    (`src/lingtai/tools/pad/_pad.py:48-58`), `_is_text_file`
    (`src/lingtai/tools/pad/_pad.py:61-73`).
  - `_pad_edit()` (`src/lingtai/tools/pad/_pad.py:81-122`) — write content plus
    optional file imports to `system/pad.md`, then reload.
  - `_pad_load()` (`src/lingtai/tools/pad/_pad.py:125-167`) — load
    `system/pad.md` plus the pinned append-files into the prompt.
  - `_pad_append()` (`src/lingtai/tools/pad/_pad.py:170-211`) — set, clear, or
    query the list of files pinned as read-only pad reference.

## Connections

- **Inbound:** `handle()` is called by the tool dispatcher (via
  `base_agent._dispatch_tool`). `boot()` is called during agent construction by
  the generic intrinsic-boot loop in
  `src/lingtai/kernel/base_agent/__init__.py:788-796`.
- **Inbound (cross-module):** `_pad_load` is imported by
  `src/lingtai/agent.py:1789-1790` (`_reload_prompt_sections`) as the single
  canonical composer of the `pad` prompt section, and `boot` is re-run by
  `src/lingtai/agent.py:1561-1567` after a refresh so the post-molt hook is
  re-registered on the cleared hook list.
- **Registration:** `src/lingtai/tools/registry.py:50-66` wires `pad` into
  `INTRINSICS`; `src/lingtai/kernel/tool_result_summary.py` lists it in
  `_LTP_V2_MIGRATED_FAMILIES`; `src/lingtai/tools/daemon/__init__.py` lists it
  in `EMANATION_BLACKLIST`.
- **Outbound:** `..tool_family` for schema composition and dispatch,
  `..tool_family.manual` for the reserved child, `.._manual` for the installed
  manual loader, and `lingtai.kernel.token_counter` lazily inside
  `_pad_append` for the 100k-token ceiling.
- **Data flow:** all state is filesystem state under the agent working
  directory — `system/pad.md` and `system/pad_append.json`. The prompt `pad`
  section is derived, written through `agent._prompt_manager`.

## Composition

The parent [`src/lingtai/tools/ANATOMY.md`](../ANATOMY.md) owns the registry
and the tool package map. The paired
[`CONTRACT.md`](CONTRACT.md) owns pad's interface promises — the closed
envelope, the destructive-rewrite and pinning semantics, and the settings
posture — and this anatomy does not restate them. The generic composition
infrastructure is [`../tool_family/ANATOMY.md`](../tool_family/ANATOMY.md).
[`../psyche/ANATOMY.md`](../psyche/ANATOMY.md) is the structurally relevant
sibling: pad's three actions were psyche leaves before the split, and psyche
retains the molt that reloads pad's section afterwards.
[`pad-manual`](../../intrinsic_skills/pad-manual/SKILL.md) teaches the
capability.

## State

Persistent: `system/pad.md` (the pad body) and `system/pad_append.json` (the
pinned reference list), both under `agent._working_dir`. Ephemeral: none owned
at module level — the family is rebuilt per `handle()` call, and the
module-level `_FAMILY` is schema-only and never dispatches.

## Notes

Pad survives a molt: the durable files are untouched by the shed, and the
post-molt hook this package registers reloads them into the fresh session's
prompt. The pre-split `psyche(action="pad_*")` call shape is not a compatibility
alias — it is simply an unknown psyche action and fails loudly.

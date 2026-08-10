---
name: psyche-tool-contract
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/psyche/ANATOMY.md
  - src/lingtai/tools/psyche/__init__.py
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/context/CONTRACT.md
  - src/lingtai/tools/pad/CONTRACT.md
  - src/lingtai/tools/lingtai/CONTRACT.md
  - src/lingtai/tools/knowledge/CONTRACT.md
  - src/lingtai/tools/skills/CONTRACT.md
  - src/lingtai/intrinsic_skills/psyche-manual/SKILL.md
  - tests/test_psyche_family.py
maintenance: |
  This component contract is governed by the root CONTRACT.md and owns the one
  public `psyche` root. Keep the paired ANATOMY.md, the psyche-manual
  routing table, the four domain Contracts it points to, the glossary
  resources, and tests/test_psyche_family.py in sync. Bump contract_version
  for any change to the public action inventory or to the read-only promise.
  Follow the root Anatomy/Contract pairing and ownership rules, report
  mismatches, and do not duplicate or auto-fix the rule here.
---
# Psyche tool contract

## Purpose
Guarded by: [PY001](BEHAVIORS.md#behavior-py001)


`psyche` is the single mandatory, model-visible LTP v2 family for the four
durable domains that survive a molt. The name states the governing human
contract exactly:

> pad + lingtai + knowledge + skills = psyche

It is a pure manual router. Its entire public inventory is manual loading, and it
owns no domain state of its own.

It replaces four former public roots (`pad`, `lingtai`, `knowledge`, `skills`) as
a clean break. Those roots, the `pad.append` action, and the `skills.info` /
`knowledge.info` actions are retired with no alias, wrapper, or compatibility
path; those tool names are unknown and fail loudly. The domains' capabilities did
not move to this family — they moved to private lifecycle ownership documented in
the four Contracts listed in `related_files`.

### Root reuse is not action compatibility

The name `psyche` previously belonged to a different family whose actions were
`lingtai_update`, `lingtai_load`, `pad_edit`, `pad_load`, `pad_append`,
`context_molt`, `name_set`, `name_nickname`, and `manual`. That family was
dissolved: its lifecycle actions moved to `context`
(`molt | summarize | rebuild | manual`) and its name actions to `system`.

Reusing the root name grants none of them, and the two cases are distinct:

- **The eight old non-`manual` spellings are unknown actions.**
  `lingtai_update`, `lingtai_load`, `pad_edit`, `pad_load`, `pad_append`,
  `context_molt`, `name_set`, and `name_nickname` — together with the lifecycle
  verbs that now belong to `context` (`molt`, `summarize`, `rebuild`) — fail
  before any I/O with no alias, wrapper, or compatibility path.
- **The spelling `manual` is deliberately reused, with new semantics.** It is a
  current, accepted action, so a `manual` call is NOT rejected. What it returns
  is only the new durable-self routing table (`psyche-manual`, the five-way map
  over Pad / 灵台 / Knowledge / Skills). It never returns the dissolved family's
  manual or body, and accepting it grants no compatibility with any other old
  action.

A Contract statement that "no `psyche` root exists" is historical and now false
about the *root*. The normative statement is narrower and remains true: no old
`psyche` action is reachable, and the one reused action name carries only its
new meaning.

### The `substrate` prompt section is unrelated and unchanged

The kernel-owned `substrate` *prompt section*
(`lingtai/prompts/substrate/substrate.md` → `system/substrate.md`) keeps its
name, content, ownership, and render order. This family briefly carried the name
`substrate` as a public root; that root is gone, and the prompt section was never
part of it. Nothing keys the two together.

## Behavior

Agents MUST treat every `psyche` action as read-only. No action authors,
edits, pins, installs, migrates, rescans a catalog, writes a prompt or source
file, or reloads prompt state.

To change a durable source, an agent MUST use the generic text operations —
`file.write` for a full create/overwrite, `file.edit` for exact replacement — on
that domain's own source, and then apply the change with one explicit
`context(action="rebuild", input={}, reasoning="...")` or let passive
refresh/molt reconstruction apply it.
File mutation never hot-loads the prompt.

Agents SHOULD read the relevant domain manual before acting on a domain they do
not already know, and SHOULD leave root `summarize` false so exact procedure and
constraints are preserved.

Coding agents MUST keep this contract, the paired Anatomy, the psyche manual,
and the focused tests synchronized whenever the action inventory or the
read-only promise changes.

## Port

The strict LTP v2 root envelope is exactly `action`, `input`, `reasoning`, and
optional root `summarize`, with `additionalProperties: false`; `action`, `input`,
and `reasoning` are required. The public action inventory is exactly:

| Action | Input | Result |
|---|---|---|
| `pad` | strict empty `{}` | flat `{status, manual, manual_path}` (+ degraded `error`) — `pad-manual` |
| `lingtai` | strict empty `{}` | same shape — `lingtai-manual` |
| `knowledge` | strict empty `{}` | same shape — the installed knowledge manual |
| `skills` | strict empty `{}` | same shape — the installed skills manual |
| `manual` | strict empty `{}` | same shape — `psyche-manual`, the routing table |

Every call carries required root `action`, `input`, and `reasoning`; a public
call is spelled `psyche(action="<domain>", input={}, reasoning="...")`. All
five children share one strict-empty `input` schema, so every `input` key is an
unknown key. Unknown or missing actions, any `input` key, non-object `input`,
unknown root fields, and a non-boolean root `summarize` fail with the LTP v2
envelope errors before any file is read. Root `summarize`, `reasoning`, and the
intrinsic-only `_tc_id` never become child input.

## Adapters

Dispatch and schema composition are the generic `tool_family` infrastructure. All
five children are built by the shared `build_manual_child` loader, so there is one
loader, one input schema, and one result adapter for the whole family — no
per-domain handler exists to acquire a side effect. The flat
`{status, manual, manual_path}` presentation shape is rebuilt strictly after
dispatch in this package's own Host layer, per the no-double-wrap rule.

`psyche` is a mandatory intrinsic: `tools/registry.py` wires it through
`INTRINSICS`, and it composes its dispatching family per call rather than owning
per-Agent state.

## Contract rules

- Schema and dispatch derive from the same fixed child registry; the advertised
  action enum cannot drift from the dispatch keys.
- Every child is mutation-free. A future mutating action does not belong in this
  family; durable mutation has exactly one owner, `file`.
- The four domain actions load the domains' existing manuals as progressively
  disclosed references. This router MUST NOT copy those manual bodies inline.
- Catalog composition, configured Skills paths, disabled-domain behavior, and the
  one-time Knowledge legacy migration remain owned by those capabilities'
  private `setup()`/refresh lifecycle and MUST NOT be reachable from any
  `psyche` action.
- Full active `context.rebuild` and passive refresh/molt reconstruction re-read
  and recompose all enabled canonical sections once and publish one prompt; this
  family participates in none of it.
- `psyche` is in `_LTP_V2_MIGRATED_FAMILIES` and `EMANATION_BLACKLIST`.
- No `psyche` settings file exists at either level, and the manual says so.
- `summarize` profile: **short-result** for every action.

## Contract tests

```bash
python -m pytest -q tests/test_psyche_family.py
```

These pin the exact five-action inventory and order, the strict-empty input on
every child, pre-I/O rejection of unknown actions and smuggled input keys, that
each action returns its intended manual, that no action mutates disk or prompt,
the absence of the four old public roots and of `pad.append` / `skills.info` /
`knowledge.info`, and both provider wire shapes.

## Maintenance

Keep `related_files` complete and repo-relative, including the paired
`ANATOMY.md`, the psyche manual, the four domain Contracts, and the contract
tests. Update the Port, this contract, the manual, and the tests together when
the action inventory or the read-only promise changes; update the paired Anatomy
when structure changes. Follow the root Anatomy/Contract pairing and ownership
rules, report mismatches, and do not duplicate or auto-fix the rule here.

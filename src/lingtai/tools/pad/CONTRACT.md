---
name: pad-contract
tool: pad
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/pad/ANATOMY.md
  - src/lingtai/tools/pad/__init__.py
  - src/lingtai/tools/pad/_pad.py
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/psyche/CONTRACT.md
  - src/lingtai/kernel/tool_result_summary.py
  - src/lingtai/intrinsic_skills/pad-manual/SKILL.md
  - tests/test_pad_lingtai_split.py
  - tests/test_pad.py
maintenance: |
  This component contract is governed by the root CONTRACT.md. Keep
  related_files as repo-relative paths to real files, including the paired
  ANATOMY.md and the pad-manual both owner twins must carry. If behavior and
  this contract disagree, the code is the source of truth — fix the contract in
  the same change and bump contract_version on breaking contract edits. pad's
  schema composition and envelope dispatch build on the generic tool_family
  package; keep that link current when either side's boundary changes.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not
  duplicate or auto-fix the rule here.
---

# Pad capability contract

## Purpose

`pad` is the agent's sketchboard in its own system prompt: `system/pad.md`
plus the pinned read-only reference files listed in `system/pad_append.json`.
It is a model-visible LTP v2 ToolFamily root and a mandatory intrinsic.

Pad was previously reached through three `psyche` leaves (`pad_edit`,
`pad_load`, `pad_append`). This contract governs the split that made it an
independent root: `pad` is a concept parallel to `knowledge` and `skills`, not
a leaf of the agent's context lifecycle. **The split moved the public root and
the action spelling only.** Every operation-level success payload, error
string, log event, and persistence path is exactly what it was under `psyche`;
the handlers in `_pad.py` are the same functions, moved with their family. The
implementation lives in `src/lingtai/tools/pad/`; the code is the source of
truth.

## Behavior

- Agents call `pad(action=..., input={...}, reasoning='why')`. There is no
  compatibility alias: `psyche(action='pad_edit'|'pad_load'|'pad_append')` is an
  unknown psyche action and fails loudly.
- `edit` is a **destructive full rewrite** of the pad body. An agent MUST
  include everything it intends to keep. A bare call carrying neither `content`
  nor `files` is refused rather than silently clearing the pad.
- `load` and `manual` are read-only with respect to durable agent state.
  `load` writes only the prompt section it composes, which is derived state.
- Agents tending the pad before a molt MUST follow `pad-manual`; the molt
  procedure itself remains owned by `psyche` and `psyche-manual`.
- A coding agent changing pad's actions, inputs, limits, or persistence paths
  MUST update this contract, the paired Anatomy, `pad-manual`, and the focused
  tests in the same change.

## Port

The provider-neutral boundary is the final `FunctionSchema` composed by
`ToolFamily` from the one `_CHILD_SPECS` registry in
`src/lingtai/tools/pad/__init__.py` (`get_schema`, `handle`).

The root property set is exactly `action`, `input`, `reasoning`, and
`summarize`, with `additionalProperties: false`. `action`, `input`, and
`reasoning` are required; `summarize` is optional Host presentation and is
never action input. The action enum is `edit`, `load`, `append`, `manual` — one
canonical child each, where the child's name is simultaneously the public
action value and the dispatch key.

Each action owns one strict, closed `input` object. Declared optional fields
use the provider-compatible nullable representation; null means "absent" at
dispatch, which is what preserves `edit`'s bare-call refusal and `append`'s
null-means-read query.

| Action (was) | Required `input` | Success output | Error shapes |
|---|---|---|---|
| `edit` (`psyche`→`pad_edit`) | `content` **or** `files` (both declared, both nullable; empty content clears; FULL REWRITE) | `{status: "ok", path, size_bytes}` | `{error: "Provide content ... files, or both."}`; `{error: "Files not found: ..."}` |
| `load` (`psyche`→`pad_load`) | — (strict empty) | `{status: "ok", path, size_bytes, content_preview, append_*}` | — |
| `append` (`psyche`→`pad_append`) | `files` (nullable: `[]` clears; null returns current) | `{status: "ok", action, files, count}` | `{error: "Files not found: ..."}`; `{error: "Only text files ..."}`; `{error: "Append files total ... token limit ..."}` |
| `manual` (root `manual`) | — (strict empty) | flat `{status, manual, manual_path}` (+ `error` when degraded) | degraded `{status, ..., error}` |

An unknown or absent `action` returns
`{error: "Unknown pad action: <x>. Must be one of: edit, load, append, manual."}`.

## Adapters

Provider adapters wrap the same composed schema in their protocol-native
envelope; the root `allOf` correlating each `action` const with that action's
exact `input` survives both the Chat and Responses wires.

`boot(agent)` is the Composition-Root-side adapter the generic intrinsic boot
loop (`base_agent.__init__`) calls: it loads the pad into the prompt and
registers the post-molt reload hook. `Agent._reload_prompt_sections` and
`Agent._setup_from_init` route through the same canonical `_pad_load` composer,
so boot, refresh, and post-molt reconstruction produce byte-identical `pad`
prompt content regardless of hook order.

## Contract rules

- `summarize` guidance profile: **short-result** for every action — pad's
  payloads are small, so leave it false. Call `manual` with `summarize=false`
  so the exact procedure is not summarized away.
- The root `allOf` correlates each `action` const with that action's exact
  `input` schema, so a provider that enforces `allOf`/`if`/`then` can reject a
  mismatched pairing before invocation; `input.oneOf` discloses every action's
  exact shape in one place.
- Dispatch remains the always-authoritative, fail-closed boundary. An `input`
  key belonging to another action's branch is rejected with
  `{status: "failed", error_code: "INVALID_ARGUMENT", message: "unsupported pad input field"}`
  **before** any handler I/O — no file write, no prompt flush, no log event.
  This matters here because `edit` is a destructive full rewrite.
- A non-boolean `summarize`, an unknown root field, a non-object `input`, and
  an unhashable `action` (`[]`/`{}` from invalid JSON) each fail with a stable
  typed envelope error rather than raising out of the dispatcher.
- `reasoning`, `_reasoning`, and `summarize` never reach a child handler.
- `_tc_id` is transport metadata `base_agent._dispatch_tool` injects into every
  intrinsic's args. No pad action consumes it, so pad **drops** it at its own
  Host boundary as `soul` and `notification` do, rather than consuming it as
  `psyche`'s molt does. The shared `_ROOT_FIELDS` set is NOT widened for it.
- The reserved `manual` child is registered unwrapped, so `ToolFamily.handle()`
  returns its canonical `content`/`structuredContent` result verbatim; pad's
  flat public shape is restored post-dispatch by `_adapt_manual_result`, never
  inside the child and never as a second envelope (no double wrap). The manual
  it returns is `pad-manual` — pad's own — never a psyche-owned manual.
- `pad` is listed in `_LTP_V2_MIGRATED_FAMILIES`
  (`src/lingtai/kernel/tool_result_summary.py`), so the canonical root
  `summarize` spelling is recognized as the a-priori summary control for this
  family. Joining that allowlist is obligatory for a family that advertises
  root `summarize`, or the control would be silently ignored.
- `pad` is on the daemon `EMANATION_BLACKLIST`: it carries the same
  prompt-mutation authority `psyche` was blacklisted for, so the boundary
  follows the split rather than being lost in it.
- Pad supports no settings file at either level — no `settings/pad.json` and no
  `settings/pad.<action>.json` — and `pad-manual` says so explicitly.

## State & storage

All paths are relative to the agent working directory (`agent._working_dir`).

```text
system/pad.md            — the pad body (edit/load)
system/pad_append.json   — pinned read-only reference file list (append)
```

`edit` writes `system/pad.md`, then reloads the `pad` prompt section and
flushes the system prompt. `append` validates every path (must exist, must be a
text file) and the 100k-token ceiling **before** persisting the list, then
reloads. Append-file paths may be absolute or workdir-relative; binary files
are rejected via a null-byte plus UTF-8 check.

## Contract tests

`tests/test_pad_lingtai_split.py` is this family's local evidence, chosen for
the split's own risks: exactly one model-facing `pad` root with the exact
action order, the closed LTP v2 envelope on both wires with the `allOf`
correlation intact, per-action input isolation, cross-branch and envelope
rejection before any handler I/O, `_tc_id`/`reasoning`/`summarize` isolation
from child input, the reserved `manual` child's no-double-wrap result resolving
to `pad-manual`, the preserved destructive-rewrite and pinning semantics, the
removal of the old `psyche` pad leaves, and registry/allowlist/inventory
exposure exactly once.

`tests/test_pad.py` continues to cover per-operation depth against the new
root. Every stateful test runs in a pytest temp path, never the live workdir.

Run before merging pad changes:

```bash
python -m pytest tests/test_pad.py tests/test_pad_lingtai_split.py \
  tests/test_psyche.py tests/test_tool_family_psyche_migration.py -q
```

## Maintenance

Keep this contract and the paired `src/lingtai/tools/pad/ANATOMY.md`
reciprocal, and keep `pad-manual` listed on both twins per root
`CONTRACT.md` Design principles 3 and 4. Update the child registry, this
contract, the manual, and the focused tests together when an action, input,
limit, error shape, or persistence path changes. Whether `psyche` should later
shrink further is a separate open design question; do not decide it here.

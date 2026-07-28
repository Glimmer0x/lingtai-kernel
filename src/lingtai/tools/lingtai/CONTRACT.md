---
name: lingtai-tool-contract
tool: lingtai
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/lingtai/ANATOMY.md
  - src/lingtai/tools/lingtai/__init__.py
  - src/lingtai/tools/lingtai/_lingtai.py
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/context/CONTRACT.md
  - src/lingtai/kernel/tool_result_summary.py
  - src/lingtai/intrinsic_skills/lingtai-manual/SKILL.md
  - tests/test_pad_lingtai_split.py
  - tests/test_eigen.py
maintenance: |
  This component contract is governed by the root CONTRACT.md. Keep
  related_files as repo-relative paths to real files, including the paired
  ANATOMY.md and the lingtai-manual both owner twins must carry. If behavior and
  this contract disagree, the code is the source of truth — fix the contract in
  the same change and bump contract_version on breaking contract edits. This
  family's schema composition and envelope dispatch build on the generic
  tool_family package; keep that link current when either side's boundary
  changes. Keep the configured-identity reconstruction authority described here
  in step with init_schema.py and Agent._reload_prompt_sections.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not
  duplicate or auto-fix the rule here.
---

# LingTai capability contract

## Purpose

`lingtai` is the agent's 灵台 (character): the self-authored identity that
distinguishes it from every other agent, held in `system/lingtai.md` and
rendered into the protected `character` section of the system prompt. It is a
model-visible LTP v2 ToolFamily root and a mandatory intrinsic.

The identity was previously reached through two `psyche` leaves
(`lingtai_update`, `lingtai_load`). This contract governs the split that made it
an independent root: `lingtai` is a concept parallel to `knowledge` and
`skills`, not a leaf of the agent's context lifecycle. **The split moved the
public root and the action spelling only.** Every operation-level success
payload, error string, log event, and persistence path is exactly what it was
under `psyche`, including the configured-identity reconstruction authority; the
handlers in `_lingtai.py` are the same functions, moved with their family. The
implementation lives in `src/lingtai/tools/lingtai/`; the code is the source of
truth.

Note on the package name: the Python package is `lingtai.tools.lingtai` — the
tool family, not the top-level `lingtai` package. Python 3 has no implicit
relative imports, so absolute imports of the top-level package from inside this
one resolve normally and the shared name creates no shadowing.

## Behavior

- Agents call `lingtai(action=..., input={...}, reasoning='why')`. There is no
  compatibility alias: `psyche(action='lingtai_update'|'lingtai_load')` is an
  unknown psyche action and fails loudly.
- `update` is a **destructive full rewrite** of the identity. An agent MUST
  carry forward its whole identity rather than sending a delta; `content=""`
  clears it, which is an explicit and legitimate choice.
- `load` and `manual` are read-only with respect to durable agent state.
  `load` writes only the prompt section it composes, which is derived state.
- Agents MUST keep the 灵台 distinct from the operator `covenant`, the
  third-party `base_prompt`, and the mechanical `identity` section. This family
  is the single canonical writer of the `character` section.
- Agents tending the identity before a molt MUST follow `lingtai-manual`; the
  molt procedure itself remains owned by `psyche` and `context-manual`.
- A coding agent changing this family's actions, inputs, identity modes, or
  persistence paths MUST update this contract, the paired Anatomy,
  `lingtai-manual`, and the focused tests in the same change.

## Port

The provider-neutral boundary is the final `FunctionSchema` composed by
`ToolFamily` from the one `_CHILD_SPECS` registry in
`src/lingtai/tools/lingtai/__init__.py` (`get_schema`, `handle`).

The root property set is exactly `action`, `input`, `reasoning`, and
`summarize`, with `additionalProperties: false`. `action`, `input`, and
`reasoning` are required; `summarize` is optional Host presentation and is
never action input. The action enum is `update`, `load`, `manual` — one
canonical child each, where the child's name is simultaneously the public
action value and the dispatch key. Each action owns one strict, closed `input`
object.

| Action (was) | Required `input` | Success output | Error shapes |
|---|---|---|---|
| `update` (`psyche`→`lingtai_update`) | `content` (empty clears; FULL REWRITE) | `{status: "ok", path}` | — |
| `load` (`psyche`→`lingtai_load`) | — (strict empty) | `{status: "ok", size_bytes, content_preview}` | — |
| `manual` (root `manual`) | — (strict empty) | flat `{status, manual, manual_path}` (+ `error` when degraded) | degraded `{status, ..., error}` |

An unknown or absent `action` returns
`{error: "Unknown lingtai action: <x>. Must be one of: update, load, manual."}`.

## Identity modes

`lingtai` has two supported modes, unchanged by the split. In **forced identity
mode**, a nonempty resolved `lingtai` value — inline or loaded from
`lingtai_file` — is authoritative and is materialized into `system/lingtai.md`
during boot, refresh, and post-molt prompt reconstruction.
`lingtai(action='update')` still writes and auto-loads immediately in the
current cycle, but the configured forced value replaces it at the next
reconstruction. In **self-evolve mode**, the configured identity is absent or
empty; reconstruction leaves `system/lingtai.md` untouched, so agent-authored
changes persist across refresh and molt.

## Adapters

Provider adapters wrap the same composed schema in their protocol-native
envelope; the root `allOf` correlating each `action` const with that action's
exact `input` survives both the Chat and Responses wires.

`boot(agent)` is the Composition-Root-side adapter the generic intrinsic boot
loop (`base_agent.__init__`) calls: it loads the identity into the prompt and
registers the post-molt reload hook. `Agent._reload_prompt_sections` and
`Agent._setup_from_init` route through the same canonical `_lingtai_load`
composer, so boot, refresh, and post-molt reconstruction produce byte-identical
`character` prompt content regardless of hook order.

## Contract rules

- `summarize` guidance profile: **short-result** for every action — payloads are
  small, so leave it false. Call `manual` with `summarize=false` so the exact
  procedure is not summarized away.
- The root `allOf` correlates each `action` const with that action's exact
  `input` schema, so a provider that enforces `allOf`/`if`/`then` can reject a
  mismatched pairing before invocation; `input.oneOf` discloses every action's
  exact shape in one place.
- Dispatch remains the always-authoritative, fail-closed boundary. An `input`
  key belonging to another action's branch is rejected with
  `{status: "failed", error_code: "INVALID_ARGUMENT", message: "unsupported lingtai input field"}`
  **before** any handler I/O — no file write, no prompt flush, no log event.
  This matters here because `update` is a destructive full rewrite of identity.
- A non-boolean `summarize`, an unknown root field, a non-object `input`, and
  an unhashable `action` (`[]`/`{}` from invalid JSON) each fail with a stable
  typed envelope error rather than raising out of the dispatcher.
- `reasoning`, `_reasoning`, and `summarize` never reach a child handler.
- `_tc_id` is transport metadata `base_agent._dispatch_tool` injects into every
  intrinsic's args. No lingtai action consumes it, so this family **drops** it
  at its own Host boundary as `soul` and `notification` do, rather than
  consuming it as `psyche`'s molt does. The shared `_ROOT_FIELDS` set is NOT
  widened for it.
- The reserved `manual` child is registered unwrapped, so `ToolFamily.handle()`
  returns its canonical `content`/`structuredContent` result verbatim; the flat
  public shape is restored post-dispatch by `_adapt_manual_result`, never
  inside the child and never as a second envelope (no double wrap). The manual
  it returns is `lingtai-manual` — this family's own — never a psyche-owned
  manual.
- `lingtai` is listed in `_LTP_V2_MIGRATED_FAMILIES`
  (`src/lingtai/kernel/tool_result_summary.py`), so the canonical root
  `summarize` spelling is recognized as the a-priori summary control for this
  family. Joining that allowlist is obligatory for a family that advertises
  root `summarize`, or the control would be silently ignored.
- `lingtai` is on the daemon `EMANATION_BLACKLIST`: it carries exactly the
  identity-mutation authority `psyche` was blacklisted for, so the boundary
  follows the split rather than being lost in it.
- This family supports no settings file at either level — no
  `settings/lingtai.json` and no `settings/lingtai.<action>.json` — and
  `lingtai-manual` says so explicitly. The configured-identity value described
  under "Identity modes" comes from the agent manifest, not an LTP settings
  file.

## State & storage

All paths are relative to the agent working directory (`agent._working_dir`).

```text
system/lingtai.md  — the self-authored identity → the protected `character` section
```

`update` writes `system/lingtai.md`, then reloads the `character` prompt
section and flushes the system prompt. `load` composes `character` from
`system/lingtai.md` alone; an empty or missing file deletes the section. Neither
action touches `system/covenant.md`, which `Agent._reload_prompt_sections` owns.

## Contract tests

`tests/test_pad_lingtai_split.py` is this family's local evidence, chosen for
the split's own risks: exactly one model-facing `lingtai` root with the exact
action order, the closed LTP v2 envelope on both wires with the `allOf`
correlation intact, per-action input isolation, cross-branch and envelope
rejection before any handler I/O, `_tc_id`/`reasoning`/`summarize` isolation
from child input, the reserved `manual` child's no-double-wrap result resolving
to `lingtai-manual`, the preserved destructive-rewrite semantics and the
`character`-section writer identity, the removal of the old `psyche` lingtai
leaves, and registry/allowlist/inventory exposure exactly once.

`tests/test_eigen.py` continues to cover the configured-identity reconstruction
authority (forced vs self-evolve) against the new root. Every stateful test runs
in a pytest temp path, never the live workdir.

Run before merging lingtai changes:

```bash
python -m pytest tests/test_eigen.py tests/test_pad_lingtai_split.py \
  tests/test_psyche.py tests/test_tool_family_psyche_migration.py -q
```

## Maintenance

Keep this contract and the paired `src/lingtai/tools/lingtai/ANATOMY.md`
reciprocal, and keep `lingtai-manual` listed on both twins per root
`CONTRACT.md` Design principles 3 and 4. Update the child registry, this
contract, the manual, and the focused tests together when an action, input,
identity mode, error shape, or persistence path changes. Whether `psyche`
should later shrink further is a separate open design question; do not decide it
here.

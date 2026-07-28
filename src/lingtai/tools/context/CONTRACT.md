---
name: context-contract
tool: context
contract_version: 4
related_files:
  - src/lingtai/tools/context/__init__.py
  - src/lingtai/tools/context/_molt.py
  - src/lingtai/tools/context/_session_journal.py
  - src/lingtai/tools/context/ANATOMY.md
  - src/lingtai/tools/system/CONTRACT.md
  - src/lingtai/tools/system/summarize.py
  - src/lingtai/tools/system/name.py
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/pad/CONTRACT.md
  - src/lingtai/tools/lingtai/CONTRACT.md
  - src/lingtai/kernel/tool_result_summary.py
  - src/lingtai/intrinsic_skills/context-manual/SKILL.md
  - tests/test_tool_family_context_migration.py
  - tests/test_pad_lingtai_split.py
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth — fix the contract in the
  same change and bump contract_version on breaking contract edits. context's
  schema composition and envelope dispatch build on the generic tool_family
  package; keep that link current when either side's boundary changes.
  contract_version 4 is the breaking public-ownership change: the root was
  renamed psyche -> context, the two name actions left for system, and the
  public system summarize action arrived here split into summarize/rebuild.
---

# Context capability contract

`context` is the department that owns the agent's context: `molt` (shed the
conversation, keep a briefing), `summarize` (record compact replacements for
prior tool results), and `rebuild` (apply pending summaries to the active
provider context). It is dispatched on a flat `action` enum under the LTP v2
envelope. The implementation lives in `src/lingtai/tools/context/`; the code is
the source of truth.

## Ownership boundary

This family replaces the former `psyche` root, which mixed two unrelated
concerns: the context lifecycle and the agent's name. There is **no `psyche`
root, module, or alias** at any model-visible or registry level.

Three moves define the current surface:

- **In, from `psyche`:** the context molt, renamed `psyche.context_molt` ->
  `context.molt`. Its semantics are moved, not redesigned — summary and
  session-journal gating, refusal-before-shed, `keep_tool_calls`/`keep_last`,
  archive/snapshot, `_tc_id` transport handling, the post-molt notification,
  the forced system molt, and every durable-store path are exactly what they
  were.
- **Out, to `system`:** `name_set` and `name_nickname`
  (`src/lingtai/tools/system/CONTRACT.md`). Naming is runtime identity state.
  No context action advertises `content`.
- **In, from `system`:** the public `system(action='summarize')` action, split
  into the two explicit actions `summarize` (record-only) and `rebuild`
  (apply). The former `rebuild` **boolean** is gone: the public action is the
  discriminator, so a caller cannot ask `summarize` to rebuild. The ~700-line
  engine itself stays at `src/lingtai/tools/system/summarize.py` as a private
  implementation both actions dispatch into; that module is an internal
  runtime interface, never a model-visible alias.

The working `pad` and the configured-or-self-authored `lingtai` identity were
**split out of the former family** into their own model-visible roots
(`src/lingtai/tools/pad/CONTRACT.md`, `src/lingtai/tools/lingtai/CONTRACT.md`):
they are concepts parallel to `knowledge` and `skills`, not leaves of the
context lifecycle. Their five old leaves — `pad_edit`, `pad_load`,
`pad_append`, `lingtai_update`, `lingtai_load` — carry **no compatibility
alias** and fail loudly with this family's stable unknown-action error. This
family defines no `boot()`: that boot-time work moved with those families.

### The two levels named `summarize`

The ACTION `context(action='summarize')` and the optional ROOT `summarize`
boolean coexist at different envelope levels and are unrelated. The root
boolean is the cross-cutting a-priori result-presentation control every LTP v2
family advertises (`src/lingtai/kernel/tool_result_summary.py`); the generic
dispatcher strips it, and **no child here declares a `summarize` property**, so
it is never domain input.

`context` is migrated to the LingTai Tool Protocol v2 shape defined in
`src/lingtai/tools/CONTRACT.md` and builds its schema composition and envelope
dispatch on the generic `src/lingtai/tools/tool_family/` infrastructure. The
public tool name, every operation, every **operation-level** success payload
and error, every log event, and every persistence path are exactly what they
were before that migration — the handlers themselves are untouched. Only the
argument *shape* changed, and with it the **envelope** layer: envelope
validation is new (see §Envelope enforcement), and the former
`Unknown object:` / `Invalid action ... for <obj>` guards are collapsed into one
`Unknown context action:` error. Those envelope-level differences are the
migration; operation-level parity is what is preserved. The former two-key
`(object, action)` matrix is now one flat `action` enum — each pre-migration
pair became exactly one action, the same collapse `notification` made for its
three atomic dismiss verbs. That migration added, renamed, and merged nothing;
the only subsequent inventory change is the pad/lingtai split described above,
which *removed* five actions to their own roots without touching the shape or
semantics of the ones that remain.

## Routing Card

**Use this when:**
- You are reviewing the context molt machinery — snapshotting, history archive,
  keep-lists, and the post-molt reminder.
- You are reviewing tool-result compaction: `summarize` (record-only) or
  `rebuild` (apply pending summaries to the active provider context).

**Do not use this for:**
- The pad (`system/pad.md`) or the configured-or-self-authored identity
  (`system/lingtai.md` → `character` prompt section): those are the separate
  `pad` and `lingtai` families
  (`src/lingtai/tools/pad/CONTRACT.md`, `src/lingtai/tools/lingtai/CONTRACT.md`).
- The agent's true name or nickname: those are
  `system(action='name_set'|'name_nickname')`
  (`src/lingtai/tools/system/CONTRACT.md`). Molt sheds *history*; `rebuild`
  reapplies the *active context* from pending summaries; neither touches
  identity, and no context action renames an address or working directory.
- Notification dismissal (including the post-molt reminder): the reminder is
  dismissed via the `notification` tool (`src/lingtai/tools/notification/CONTRACT.md`).
- Code navigation only: read `src/lingtai/tools/context/ANATOMY.md`.

**Fast paths:** the action inventory -> §Tool surface; molt/snapshot
paths -> §State & storage.

## Scope

- Canonical tool name: `context`.
- The root property set is exactly `action`, `input`, `reasoning`, and
  `summarize`, with `additionalProperties: false`. `action`, `input`, and
  `reasoning` are required; `summarize` is optional Host presentation and is
  never action input. The action enum is exactly `molt`, `summarize`,
  `rebuild`, `manual` — one canonical child each, where the child's name is
  simultaneously the public action value and the dispatch key.
- Each action owns one strict, closed `input` object. Declared optional fields
  use the provider-compatible nullable representation; null means "absent" at
  dispatch, which is what preserves `molt`'s nullable
  `keep_tool_calls`/`keep_last` semantics and makes `rebuild`'s
  `{}` the ordinary no-new-items call. `rebuild.items` is the one field this
  family leaves genuinely OPTIONAL (absent from its branch's `required`) rather
  than "required but nullable", because a bare `input={}` is its documented
  ordinary call and must be schema-valid; an explicit `{"items": null}` means
  the same thing and stays accepted for provider compatibility.
- Root `summarize` guidance profile: **short-result** for every action — this
  family's payloads are small, so leave it false. Call `manual` with
  `summarize=false` so the exact molt procedure is not summarized away.
- `input.summary` on `molt` is a *domain* field the molt itself
  consumes (the agent's retrospective), explicitly permitted by
  `src/lingtai/tools/CONTRACT.md` "Envelope". It is not the root
  result-summarization control, which is the separate `summarize` boolean.
- Non-goals: notification verbs, the agent's name/nickname (now `system`),
  physical address/workdir rename, mailbox actions, and — after the split — pad
  and identity editing.
- Former name `anima` is not a compatibility alias, and neither is the
  pre-migration flat `(object, action)` call shape nor any of the five removed
  `pad_*`/`lingtai_*` leaves: each is simply an unknown action and fails loudly.

## Tool surface

Schema and dispatch both live in `src/lingtai/tools/context/__init__.py`
(`get_schema`, `handle`), composed by the generic `ToolFamily` from the one
`_CHILD_SPECS` registry so the advertised actions are by construction the ones
dispatch registers.

Inputs below are fields of that action's own `input` object, never of the root.
Each row's pre-migration `(object, action)` origin is named so the preserved
inventory is auditable.

| Action (was) | Required `input` | Optional `input` | Success output | Error shapes |
|---|---|---|---|---|
| `molt` (`psyche.context_molt`) | `summary`, `session_journal_path` | `keep_tool_calls`, `keep_last` (nullable) | `{status: "ok", note, molt_count, tokens_before/after/shed, kept_*, archive_path, summary_path, session_journal_path}` | `{error: "summary is required ..."}`; journal-validation `{error}`; `{error: "No active chat session to molt."}`; `{error, unmatched_ids}` / `{error, missing_call_ids}` for bad keep-lists; `{error: "keep_last must be ..."}` |
| `summarize` (`system.summarize`, `rebuild=false`) | `items` (non-empty) | — | `{status: "ok"/"partial", mode: "summarize", summarized, failed, items, pending_summary_totals, context, reconstruction, notification_threshold_chars}` | `{status: "error", reason: "missing_items"/"runtime_threshold_change_not_supported"}`; per-item `not_found`, `already_summarized`, `missing_tool_call_id`, `missing_summary`, `no_chat_session` |
| `rebuild` (`system.summarize`, `rebuild=true`) | — (`input={}` is the ordinary call) | `items` (optional, nullable; omit/null = apply already-pending) | `{status: "ok"/"partial", mode: "rebuild", rebuild_requested, marked_done, applied_summary_totals, context, reconstruction, notification_threshold_chars}` | `{status: "error", reason: "no_chat_session"}`; same per-item errors when `items` is given |
| `manual` (root `manual`) | — (strict empty) | — | flat `{status, manual, manual_path}` (+ `error` when missing) | degraded `{status, ..., error}` |

An unknown or absent `action` returns
`{error: "Unknown context action: <x>. Must be one of: ..."}`. The former
`Unknown object:` / `Invalid action ... for <obj>` guards are collapsed into
that one error, because there is no longer a valid-object/invalid-action pair
to distinguish.

### Envelope enforcement

- The root `allOf` correlates each `action` const with that action's exact
  `input` schema, so a provider that enforces `allOf`/`if`/`then` can reject a
  mismatched pairing before invocation; `input.oneOf` discloses every action's
  exact shape in one place.
- Dispatch remains the always-authoritative, fail-closed boundary. An `input`
  key belonging to another action's branch (e.g. `action='summarize'` with
  `input={'summary': ...}`) is rejected with
  `{status: "failed", error_code: "INVALID_ARGUMENT", message: "unsupported context input field"}`
  **before** any handler I/O — no file write, no context shed, no log event.
  This matters more here than for most families: `molt` is irreversible
  and `rebuild` mutates the active provider context. (The two destructive full rewrites
  that used to sit behind this root, `pad_edit` and `lingtai_update`, moved to
  the `pad` and `lingtai` families, which state the same rule for themselves.)
- A non-boolean `summarize`, an unknown root field, a non-object `input`, and
  an unhashable `action` (`[]`/`{}` from invalid JSON) each fail with a stable
  typed envelope error rather than raising out of the dispatcher.
- `reasoning`, `_reasoning`, and `summarize` never reach a child handler.
- `_tc_id` is transport metadata `base_agent._dispatch_tool` injects into every
  intrinsic's args. `context` is the one migrated family that genuinely
  **consumes** it — `molt` locates the molt's own `ToolCallBlock` by
  that wire id to replay it into the fresh session — rather than merely
  dropping it as `soul`, `notification`, `system`, and `email` do. It is therefore stripped from
  the closed root at this family's own Host boundary and threaded to that single
  handler out-of-band (the seam `avatar` uses for its spawn mission brief). The
  shared `_ROOT_FIELDS` set is NOT widened for it, and no other action can
  observe it.
- `context` is listed in `_LTP_V2_MIGRATED_FAMILIES`
  (`src/lingtai/kernel/tool_result_summary.py`), so the canonical root
  `summarize` spelling is recognized as the a-priori summary control for this
  family. Joining that allowlist is obligatory for a family that advertises
  root `summarize`, or the control would be silently ignored.

### Synthesized system-forced molt pair

`context_forget` synthesizes a complete `(ToolCallBlock, ToolResultBlock)`
pair. That call block is replayed to the provider as an assistant `tool_use`
block, so it is a **model-visible example of how to call `context`** and MUST
carry the same envelope the schema advertises: `action: "molt"`, the
system-authored summary inside `input`, and a Host-authored `reasoning`
(`SYSTEM_FORCED_MOLT_REASONING`) stating plainly that the agent did not
initiate the call. `_initiator`/`_source` stay **outside** `input` — they are
Host provenance metadata, not action input, and `molt`'s `input` schema
does not declare them.

The synthesized `input` MUST carry **every** key `molt`'s schema marks
required, so the block is envelope-shaped and branch-key-exact rather than a
partial object. `keep_tool_calls`/`keep_last` are declared nullable, so their
explicit `null`s are schema-valid.

**The system-forced pair is deliberately NOT fully schema-valid, and this
contract does not claim it is.** `session_journal_path` is declared required and
**non-nullable** (`"type": "string"`), so the synthesized `null` is
*type-invalid* for that one field. This is an accepted, documented residual, not
an oversight: no value here is simultaneously honest and schema-valid. A forced
molt has no journal — the kernel synthesized the molt, and there was no agent
turn to author one. Any string would fabricate a journal path; `""` would be
type-valid but a lie, and gate-refused anyway. `null` is the least-wrong value
because it states the absence truthfully. The alternative — declaring the field
nullable in the public schema — is rejected because it would weaken the
model-facing advertisement of a hard gate for every caller, to accommodate one
Host-synthesized exemplar.

The residual is bounded and fails safe. Replayed assistant `tool_use` blocks are
not provider-validated, so nothing fails at runtime. A model that imitates this
exemplar and sends `session_journal_path: null` has that null stripped by
`_strip_nulls` and is then refused by the **unconditional** journal gate with an
actionable recovery message, **before any context is shed** — `molt_count` and
history untouched. That refusal is the designed lesson, not a failure mode.

The agent-initiated path carries no such residual: `_context_molt` replays the
agent's own call block verbatim, and that call was schema-conformant on the way
in, so the replayed block is fully valid including a real
`session_journal_path`.

This is not cosmetic: a model imitating its own history and sending the
pre-migration flat `{"object": "context", "action": "molt"}` succeeded before
the migration and now fails as an unknown action, and one imitating a partial
`input` would send a call the advertised schema rejects on branch keys. Any
future producer of synthesized `context` calls carries the same obligation — and
the same duty to describe any residual invalidity precisely rather than round it
up to "valid".

`base_agent.turn._is_context_molt_call` reads only `args["action"]`, the
post-migration spelling. That is a read path over the live batch, **not** a
second accepted call shape: nothing in dispatch admits the flat form.

Note: system-forced molt is a separate code path (`context_forget`), invoked by
the kernel on a `.clear` signal, not an agent-callable `(object, action)`. It
synthesizes its own `context(action='molt', input={...})` call/result
pair, carrying `_initiator='system'` as root provenance.

## State & storage

All paths are relative to the agent working directory (`agent._working_dir`).

```text
system/summaries/molt_<count>_<ts>.md  — molt retrospective (agent- or system-authored)
history/snapshots/snapshot_<count>_<ts>.json — frozen pre-molt ChatInterface substrate
history/chat_history.jsonl             — live chat history (moved on molt)
history/chat_history_archive.jsonl     — appended pre-molt history on each molt
.notification/post-molt.json           — post-molt "resume work" reminder (published on molt)
```

`system/pad.md`, `system/pad_append.json`, and `system/lingtai.md` are no longer
context state: they belong to the `pad` and `lingtai` families, whose own
post-molt hooks reload their prompt sections after a shed.

- `context molt` writes a snapshot, wipes the session, increments `molt_count`
  (persisted to `init.json` manifest), archives + unlinks `chat_history.jsonl`,
  replays `keep_last`/`keep_tool_calls` into the fresh session, writes a summary,
  and publishes `.notification/post-molt.json`. Snapshot/summary writes are
  best-effort and never block the molt.

## Cross-platform invariants

- All file access is via `pathlib.Path` (`read_text`/`write_text`,
  `mkdir`, `unlink`) with UTF-8 for text sections; snapshot/summary writes go to
  a `.tmp` sibling then `Path.replace` for atomicity. DOCUMENT.
- No subprocess/PTY; molt operates on in-memory `ChatInterface` objects plus the
  history-file archive. DOCUMENT — no platform-specific behavior; all file access
  via pathlib.

## Anchored claims

| Claim | Source | Test |
|---|---|---|
| `context` is a wired intrinsic; no `psyche` root or `anima` alias survives | `src/lingtai/tools/context/__init__.py`, `src/lingtai/tools/registry.py` | `tests/test_context.py::test_context_is_intrinsic`, `tests/test_context.py::test_anima_alias_removed`, `tests/test_tool_family_context_migration.py::test_no_psyche_root_survives_anywhere`, `tests/test_pad.py::test_intrinsics_include_context_pad_and_lingtai` |
| The retained actions keep their exact pre-split names, order, and semantics; the five `pad_*`/`lingtai_*` leaves are removed with no alias | `src/lingtai/tools/context/__init__.py:_CHILD_SPECS`, `get_schema` | `tests/test_tool_family_context_migration.py::test_one_public_context_root_with_the_exact_action_inventory`, `tests/test_pad_lingtai_split.py::test_context_no_longer_exposes_pad_or_lingtai_leaves` |
| The root is the closed LTP v2 envelope with required `reasoning`, and `object` is gone with no alias | `src/lingtai/tools/context/__init__.py:get_schema` | `tests/test_tool_family_context_migration.py::test_the_root_is_the_closed_ltp_v2_envelope`, `tests/test_context.py::test_context_schema_is_the_closed_ltp_v2_envelope` |
| Each action advertises only its own `input`; schema and dispatch come from one registry | `src/lingtai/tools/context/__init__.py:_CHILD_SPECS`/`_build_children` | `tests/test_tool_family_context_migration.py::test_each_action_advertises_only_its_own_input`, `::test_schema_and_dispatch_come_from_one_registry` |
| Cross-action `input` is rejected before any handler I/O | `src/lingtai/tools/context/__init__.py:handle` via `tool_family.ToolFamily.handle` | `tests/test_tool_family_context_migration.py::test_wrong_branch_input_is_rejected_before_any_handler_io` |
| `_tc_id` is stripped from the closed root yet still reaches the molt handler, and no other action | `src/lingtai/tools/context/__init__.py:handle`, `_MOLT_ENVELOPE_KEYS` | `tests/test_tool_family_context_migration.py::test_tc_id_is_isolated_to_the_molt_handler`, `::test_reasoning_and_summarize_never_reach_a_handler` |
| One public `context` root on both wires with the `allOf` action/input correlation intact | `src/lingtai/tools/context/__init__.py:get_schema`, `kernel/base_agent/tools.py:_build_tool_schemas` | `tests/test_tool_family_context_migration.py::test_one_context_root_survives_both_wires_with_action_input_correlation` |
| The synthesized system-forced molt pair is envelope-shaped and branch-key-exact (every required `input` key present), but intentionally type-invalid on the non-nullable `session_journal_path`; a model imitating it is refused by the journal gate before any shed | `src/lingtai/tools/context/_molt.py:context_forget` | `tests/test_tool_family_context_migration.py::test_system_forced_molt_synthesizes_the_current_envelope`, `::test_molt_refuses_before_shedding_on_an_invalid_journal` |
| The agent's own replayed molt call block carries the full strict input the agent actually sent, including a real `session_journal_path` | `src/lingtai/tools/context/_molt.py:_context_molt` (verbatim replay) | `tests/test_tool_family_context_migration.py::test_successful_molt_lifecycle_in_a_disposable_workdir` |
| The kernel's molt-batch deferral reads the migrated `action` spelling | `src/lingtai/kernel/base_agent/turn.py:_is_context_molt_call` | `tests/test_tool_family_context_migration.py::test_kernel_detects_the_migrated_molt_call_shape` |
| `context` is on the kernel `summarize` allowlist, and its molt `summary` is domain input rather than that control | `src/lingtai/kernel/tool_result_summary.py:_LTP_V2_MIGRATED_FAMILIES` | `tests/test_tool_family_context_migration.py::test_context_is_on_the_ltp_v2_summarize_allowlist` |
| The reserved `manual` child returns the canonical result unwrapped; this family's flat public shape is restored post-dispatch | `src/lingtai/tools/context/__init__.py:_adapt_manual_result`, `tool_family/manual.py:build_manual_child` | `tests/test_tool_family_context_migration.py::test_manual_child_returns_the_canonical_result_unwrapped`, `::test_manual_public_result_is_flattened_post_dispatch`, `tests/test_intrinsic_manual_actions.py` |
| Identity and pad behavior moved with their families and is claimed there, not here | `src/lingtai/tools/lingtai/CONTRACT.md`, `src/lingtai/tools/pad/CONTRACT.md` | `tests/test_pad_lingtai_split.py`, `tests/test_pad.py`, `tests/test_eigen.py` |
| `context molt` returns the faint-memory result and shed counts | `src/lingtai/tools/context/_molt.py:_context_molt` | `tests/test_context.py::test_molt_returns_faint_memory` |
| Molt writes a summary file under `system/summaries/` | `src/lingtai/tools/context/_snapshots.py:_write_molt_summary` | `tests/test_context.py::test_molt_writes_summary_file_for_agent_path` |
| System-forced molt (`context_forget`) still works and writes its own summary | `src/lingtai/tools/context/_molt.py:context_forget` | `tests/test_context.py::test_context_forget_still_works`, `tests/test_context.py::test_context_forget_writes_summary_file_for_system_path` |
| A failed summary write does not block the molt | `src/lingtai/tools/context/_molt.py`, `_snapshots.py` | `tests/test_context.py::test_summary_write_failure_does_not_block_molt` |
| An unknown action (including the pre-migration flat shape) is rejected before any handler runs | `src/lingtai/tools/context/__init__.py:handle` | `tests/test_context.py::test_unknown_action_is_rejected`, `tests/test_context.py::test_pre_migration_object_action_shape_is_rejected`, `tests/test_tool_family_context_migration.py::test_unhashable_or_unknown_action_renders_the_stable_error` |
| The two name actions are NOT owned here — they moved to `system` and no context action advertises `content` | `src/lingtai/tools/system/name.py`, `src/lingtai/tools/system/CONTRACT.md` | `tests/test_tool_family_system_migration.py::test_name_actions_preserve_identity_semantics`, `tests/test_tool_family_context_migration.py::test_each_action_advertises_only_its_own_input` |
| `summarize` records only and never rebuilds; `rebuild` is the only applying action, and the root `summarize` boolean is never domain input | `src/lingtai/tools/context/__init__.py:_summarize_action`/`_rebuild_action` | `tests/test_tool_family_context_migration.py::test_summarize_requires_items_and_never_rebuilds`, `::test_rebuild_with_no_items_is_the_ordinary_pure_rebuild`, `::test_root_summarize_bool_is_never_domain_input_of_the_summarize_action` |
| The public `system(action='summarize')` is gone with no alias | `src/lingtai/tools/system/schema.py:ACTION_ORDER` | `tests/test_tool_family_system_migration.py::test_public_summarize_action_is_gone_and_fails_loudly` |
| `manual` mutates no durable state | `src/lingtai/tools/context/__init__.py` | `tests/test_tool_family_context_migration.py::test_read_only_actions_mutate_no_durable_state` |
| The stop path does not overwrite `system/pad.md` (now a `pad`-family fact) | `src/lingtai/tools/pad/_pad.py` | `tests/test_context.py::test_stop_does_not_overwrite_pad_md` |

## Verification matrix

| Invariant | Automated test | Manual check | Risk if broken |
|---|---|---|---|
| The action guard rejects unknowns pre-dispatch | `tests/test_context.py::test_unknown_action_is_rejected` | Call `context(action='foo', input={})` | Silent no-ops or wrong handler |
| A cross-action `input` never reaches a handler | `tests/test_tool_family_context_migration.py::test_wrong_branch_input_is_rejected_before_any_handler_io` | Send `action='summarize'` with `input={'items': [], 'summary': 'x'}` | A mis-paired call shedding context or rebuilding unexpectedly |
| Synthesized system molts stay envelope-shaped | `tests/test_tool_family_context_migration.py::test_system_forced_molt_synthesizes_the_current_envelope` | Force a molt, read the appended pair's args | History teaching a shape dispatch rejects |
| Pad/lingtai edits reload their prompt sections (now owned by those families) | `tests/test_pad.py::test_pad_edit_then_load`, `tests/test_pad_lingtai_split.py` | Edit pad, inspect prompt sections | Stale identity/notes in prompt |
| Molt archives history and increments count | `tests/test_context.py::test_molt_returns_faint_memory` | Molt, inspect `history/` + manifest | Lost history / miscounted molts |
| Molt journal gate refuses without a valid session-journal path | `src/lingtai/tools/context/_molt.py:_context_molt` (journal validation) | Molt without `session_journal_path` | Context shed with no durable trail |
| Snapshot/summary write failure is non-fatal | `tests/test_context.py::test_summary_write_failure_does_not_block_molt` | Make summaries dir unwritable, molt | A disk hiccup wedges the agent |

Run before merging context changes:

```bash
python -m pytest tests/test_context.py tests/test_pad.py \
  tests/test_tool_family_context_migration.py tests/test_pad_lingtai_split.py \
  tests/test_session_journal_gate.py \
  tests/test_eigen.py tests/test_intrinsic_manual_actions.py -q
```

## Schema and glossary ownership

- **Canonical identifiers:** function names, JSON property names, action/enum
  values, required fields, defaults, and bounds are canonical English literals.
  The schema (`get_schema()`) and description (`get_description()`) are
  language-independent; the optional `lang` argument is accepted for source
  compatibility but ignored.
- **Provider wire:** provider adapters send the global `WIRE_TOOL_DESCRIPTION`
  constant as the top-level tool description; `FunctionSchema.description`
  holds the full canonical prose rendered into `## tools`.
- **Glossary resources:** this package owns `glossary-en.md`, `glossary-zh.md`,
  and `glossary-wen.md`. Each has strict YAML frontmatter
  (`kind: tool-glossary`, `schema_version: 1`, `tool_package: tools.<pkg>`,
  `language: <lang>`). English body is empty; zh/wen bodies contain concise
  terminology mappings that quote immutable English identifiers and never offer
  localized aliases.
- **Fallback:** exact normalized language lookup, then English, then no
  appendix. Fail-closed for localized text; fail-open for tool availability.
- **Update triggers:** changing a function name, action/enum value, property
  name, or user-visible concept requires reviewing all three glossary files in
  the same PR.
- **Validation:** `python -m lingtai.tools.glossary_validator --check`.

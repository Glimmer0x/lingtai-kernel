---
name: psyche-contract
tool: psyche
contract_version: 3
related_files:
  - src/lingtai/tools/psyche/__init__.py
  - src/lingtai/tools/psyche/_molt.py
  - src/lingtai/tools/psyche/_session_journal.py
  - src/lingtai/tools/psyche/ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/pad/CONTRACT.md
  - src/lingtai/tools/lingtai/CONTRACT.md
  - src/lingtai/kernel/tool_result_summary.py
  - src/lingtai/intrinsic_skills/psyche-manual/SKILL.md
  - tests/test_tool_family_psyche_migration.py
  - tests/test_pad_lingtai_split.py
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth — fix the contract in the
  same change and bump contract_version on breaking contract edits. psyche's
  schema composition and envelope dispatch build on the generic tool_family
  package; keep that link current when either side's boundary changes.
---

# Psyche capability contract

`psyche` is the agent's true `name`/nickname and its `context` molt (shed
history, keep a briefing). It is dispatched on a flat `action` enum under the
LTP v2 envelope; the pre-migration `(object, action)` matrix is described below
only to make the preserved inventory auditable. The implementation lives in
`src/lingtai/tools/psyche/`; the code is the source of truth.

## Split boundary

The working `pad` and the configured-or-self-authored `lingtai` identity were
**split out of this family** into their own model-visible roots
(`src/lingtai/tools/pad/CONTRACT.md`, `src/lingtai/tools/lingtai/CONTRACT.md`):
they are concepts parallel to `knowledge` and `skills`, not leaves of the
context lifecycle. That split removed five actions from this family —
`pad_edit`, `pad_load`, `pad_append`, `lingtai_update`, `lingtai_load` — with
**no compatibility alias**: they are unknown psyche actions and fail loudly with
this family's stable unknown-action error.

The split is public-surface-only for this family. Every retained action name,
input, success payload, error string, log event, persistence path, and molt
semantic is exactly what it was before it, and the retained actions were not
renamed or reordered. Psyche no longer defines `boot()`: its only boot-time work
was loading the pad and identity sections and registering their post-molt
reload, and both moved with their families.

**Psyche's ultimate fate is deliberately undecided by this contract.** Whether
it should later shrink further, be renamed (`molt`/`name`/`nickname` were
considered and explicitly deferred), survive as-is, or disappear is a separate
human design decision to be made after this split's evidence exists. Do not read
the reduced surface here as a commitment either way.

`psyche` is migrated to the LingTai Tool Protocol v2 shape defined in
`src/lingtai/tools/CONTRACT.md` and builds its schema composition and envelope
dispatch on the generic `src/lingtai/tools/tool_family/` infrastructure. The
public tool name, every operation, every **operation-level** success payload
and error, every log event, and every persistence path are exactly what they
were before that migration — the handlers themselves are untouched. Only the
argument *shape* changed, and with it the **envelope** layer: envelope
validation is new (see §Envelope enforcement), and the former
`Unknown object:` / `Invalid action ... for <obj>` guards are collapsed into one
`Unknown psyche action:` error. Those envelope-level differences are the
migration; operation-level parity is what is preserved. The former two-key
`(object, action)` matrix is now one flat `action` enum — each pre-migration
pair became exactly one action, the same collapse `notification` made for its
three atomic dismiss verbs. That migration added, renamed, and merged nothing;
the only subsequent inventory change is the pad/lingtai split described above,
which *removed* five actions to their own roots without touching the shape or
semantics of the ones that remain.

## Routing Card

**Use this when:**
- You are editing the true-name/nickname handlers.
- You are reviewing the context molt machinery — snapshotting, history archive,
  keep-lists, and the post-molt reminder.

**Do not use this for:**
- The pad (`system/pad.md`) or the configured-or-self-authored identity
  (`system/lingtai.md` → `character` prompt section): those are the separate
  `pad` and `lingtai` families
  (`src/lingtai/tools/pad/CONTRACT.md`, `src/lingtai/tools/lingtai/CONTRACT.md`).
- Provider-context rebuild after summarizing: that is `system(action=
  'summarize', rebuild=true)` (`src/lingtai/tools/system/CONTRACT.md`). Molt sheds
  *history*; summarize rebuilds the *active context* from pending summaries.
- Notification dismissal (including the post-molt reminder): the reminder is
  dismissed via the `notification` tool (`src/lingtai/tools/notification/CONTRACT.md`).
- Code navigation only: read `src/lingtai/tools/psyche/ANATOMY.md`.

**Fast paths:** the action inventory -> §Tool surface; molt/snapshot
paths -> §State & storage.

## Scope

- Canonical tool name: `psyche`.
- The root property set is exactly `action`, `input`, `reasoning`, and
  `summarize`, with `additionalProperties: false`. `action`, `input`, and
  `reasoning` are required; `summarize` is optional Host presentation and is
  never action input. The action enum is `context_molt`, `name_set`,
  `name_nickname`, `manual` — one canonical child each, where the child's name
  is simultaneously the public action value and the dispatch key.
- Each action owns one strict, closed `input` object. Declared optional fields
  use the provider-compatible nullable representation; null means "absent" at
  dispatch, which is what preserves `context_molt`'s nullable
  `keep_tool_calls`/`keep_last` semantics.
- `summarize` guidance profile: **short-result** for every action — psyche's
  payloads are small, so leave it false. Call `manual` with `summarize=false`
  so the exact molt procedure is not summarized away.
- `input.summary` on `context_molt` is a *domain* field the molt itself
  consumes (the agent's retrospective), explicitly permitted by
  `src/lingtai/tools/CONTRACT.md` "Envelope". It is not the root
  result-summarization control, which is the separate `summarize` boolean.
- Non-goals: notification verbs, summarize/rebuild, mailbox actions, and — after
  the split — pad and identity editing.
- Former name `anima` is not a compatibility alias, and neither is the
  pre-migration flat `(object, action)` call shape nor any of the five removed
  `pad_*`/`lingtai_*` leaves: each is simply an unknown action and fails loudly.

## Tool surface

Schema and dispatch both live in `src/lingtai/tools/psyche/__init__.py`
(`get_schema`, `handle`), composed by the generic `ToolFamily` from the one
`_CHILD_SPECS` registry so the advertised actions are by construction the ones
dispatch registers.

Inputs below are fields of that action's own `input` object, never of the root.
Each row's pre-migration `(object, action)` origin is named so the preserved
inventory is auditable.

| Action (was) | Required `input` | Optional `input` | Success output | Error shapes |
|---|---|---|---|---|
| `context_molt` (`context`→`molt`) | `summary`, `session_journal_path` | `keep_tool_calls`, `keep_last` (nullable) | `{status: "ok", note, molt_count, tokens_before/after/shed, kept_*, archive_path, summary_path, session_journal_path}` | `{error: "summary is required ..."}`; journal-validation `{error}`; `{error: "No active chat session to molt."}`; `{error, unmatched_ids}` / `{error, missing_call_ids}` for bad keep-lists; `{error: "keep_last must be ..."}` |
| `name_set` (`name`→`set`) | `content` | — | `{status: "ok", name}` | `{error: "Name cannot be empty..."}`; `{error}` (name already set / immutable) |
| `name_nickname` (`name`→`nickname`) | `content` (empty clears) | — | `{status: "ok", nickname}` | — |
| `manual` (root `manual`) | — (strict empty) | — | flat `{status, manual, manual_path}` (+ `error` when missing) | degraded `{status, ..., error}` |

An unknown or absent `action` returns
`{error: "Unknown psyche action: <x>. Must be one of: ..."}`. The former
`Unknown object:` / `Invalid action ... for <obj>` guards are collapsed into
that one error, because there is no longer a valid-object/invalid-action pair
to distinguish.

### Envelope enforcement

- The root `allOf` correlates each `action` const with that action's exact
  `input` schema, so a provider that enforces `allOf`/`if`/`then` can reject a
  mismatched pairing before invocation; `input.oneOf` discloses every action's
  exact shape in one place.
- Dispatch remains the always-authoritative, fail-closed boundary. An `input`
  key belonging to another action's branch (e.g. `action='name_set'` with
  `input={'summary': ...}`) is rejected with
  `{status: "failed", error_code: "INVALID_ARGUMENT", message: "unsupported psyche input field"}`
  **before** any handler I/O — no file write, no context shed, no log event.
  This matters more here than for most families: `context_molt` is
  irreversible and `name_set` is set-once. (The two destructive full rewrites
  that used to sit behind this root, `pad_edit` and `lingtai_update`, moved to
  the `pad` and `lingtai` families, which state the same rule for themselves.)
- A non-boolean `summarize`, an unknown root field, a non-object `input`, and
  an unhashable `action` (`[]`/`{}` from invalid JSON) each fail with a stable
  typed envelope error rather than raising out of the dispatcher.
- `reasoning`, `_reasoning`, and `summarize` never reach a child handler.
- `_tc_id` is transport metadata `base_agent._dispatch_tool` injects into every
  intrinsic's args. Psyche is the one migrated family that genuinely
  **consumes** it — `context_molt` locates the molt's own `ToolCallBlock` by
  that wire id to replay it into the fresh session — rather than merely
  dropping it as `soul` and `notification` do. It is therefore stripped from
  the closed root at psyche's own Host boundary and threaded to that single
  handler out-of-band (the seam `avatar` uses for its spawn mission brief). The
  shared `_ROOT_FIELDS` set is NOT widened for it, and no other action can
  observe it.
- `psyche` is listed in `_LTP_V2_MIGRATED_FAMILIES`
  (`src/lingtai/kernel/tool_result_summary.py`), so the canonical root
  `summarize` spelling is recognized as the a-priori summary control for this
  family. Joining that allowlist is obligatory for a family that advertises
  root `summarize`, or the control would be silently ignored.

### Synthesized system-forced molt pair

`context_forget` synthesizes a complete `(ToolCallBlock, ToolResultBlock)`
pair. That call block is replayed to the provider as an assistant `tool_use`
block, so it is a **model-visible example of how to call `psyche`** and MUST
carry the same envelope the schema advertises: `action: "context_molt"`, the
system-authored summary inside `input`, and a Host-authored `reasoning`
(`SYSTEM_FORCED_MOLT_REASONING`) stating plainly that the agent did not
initiate the call. `_initiator`/`_source` stay **outside** `input` — they are
Host provenance metadata, not action input, and `context_molt`'s `input` schema
does not declare them.

The synthesized `input` MUST carry **every** key `context_molt`'s schema marks
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
future producer of synthesized `psyche` calls carries the same obligation — and
the same duty to describe any residual invalidity precisely rather than round it
up to "valid".

`base_agent.turn._is_context_molt_call` reads only `args["action"]`, the
post-migration spelling. That is a read path over the live batch, **not** a
second accepted call shape: nothing in dispatch admits the flat form.

Note: system-forced molt is a separate code path (`context_forget`), invoked by
the kernel on a `.clear` signal, not an agent-callable `(object, action)`. It
synthesizes its own `psyche(action='context_molt', input={...})` call/result
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
psyche state: they belong to the `pad` and `lingtai` families, whose own
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
| `psyche` is a wired intrinsic; `anima` is not an alias | `src/lingtai/tools/psyche/__init__.py` | `tests/test_psyche.py::test_psyche_is_intrinsic`, `tests/test_psyche.py::test_anima_alias_removed`, `tests/test_pad.py::test_intrinsics_include_psyche_pad_and_lingtai` |
| The retained actions keep their exact pre-split names, order, and semantics; the five `pad_*`/`lingtai_*` leaves are removed with no alias | `src/lingtai/tools/psyche/__init__.py:_CHILD_SPECS`, `get_schema` | `tests/test_tool_family_psyche_migration.py::test_one_public_psyche_root_with_the_preserved_operation_inventory`, `tests/test_pad_lingtai_split.py::test_psyche_no_longer_exposes_pad_or_lingtai_leaves` |
| The root is the closed LTP v2 envelope with required `reasoning`, and `object` is gone with no alias | `src/lingtai/tools/psyche/__init__.py:get_schema` | `tests/test_tool_family_psyche_migration.py::test_the_root_is_the_closed_ltp_v2_envelope`, `tests/test_psyche.py::test_psyche_schema_is_the_closed_ltp_v2_envelope` |
| Each action advertises only its own `input`; schema and dispatch come from one registry | `src/lingtai/tools/psyche/__init__.py:_CHILD_SPECS`/`_build_children` | `tests/test_tool_family_psyche_migration.py::test_each_action_advertises_only_its_own_input`, `::test_schema_and_dispatch_come_from_one_registry` |
| Cross-action `input` is rejected before any handler I/O | `src/lingtai/tools/psyche/__init__.py:handle` via `tool_family.ToolFamily.handle` | `tests/test_tool_family_psyche_migration.py::test_wrong_branch_input_is_rejected_before_any_handler_io` |
| `_tc_id` is stripped from the closed root yet still reaches the molt handler, and no other action | `src/lingtai/tools/psyche/__init__.py:handle`, `_MOLT_ENVELOPE_KEYS` | `tests/test_tool_family_psyche_migration.py::test_tc_id_is_isolated_to_the_molt_handler`, `::test_reasoning_and_summarize_never_reach_a_handler` |
| One public `psyche` root on both wires with the `allOf` action/input correlation intact | `src/lingtai/tools/psyche/__init__.py:get_schema`, `kernel/base_agent/tools.py:_build_tool_schemas` | `tests/test_tool_family_psyche_migration.py::test_one_psyche_root_survives_both_wires_with_action_input_correlation` |
| The synthesized system-forced molt pair is envelope-shaped and branch-key-exact (every required `input` key present), but intentionally type-invalid on the non-nullable `session_journal_path`; a model imitating it is refused by the journal gate before any shed | `src/lingtai/tools/psyche/_molt.py:context_forget` | `tests/test_tool_family_psyche_migration.py::test_system_forced_molt_synthesizes_the_current_envelope`, `::test_molt_refuses_before_shedding_on_an_invalid_journal` |
| The agent's own replayed molt call block carries the full strict input the agent actually sent, including a real `session_journal_path` | `src/lingtai/tools/psyche/_molt.py:_context_molt` (verbatim replay) | `tests/test_tool_family_psyche_migration.py::test_successful_molt_lifecycle_in_a_disposable_workdir` |
| The kernel's molt-batch deferral reads the migrated `action` spelling | `src/lingtai/kernel/base_agent/turn.py:_is_context_molt_call` | `tests/test_tool_family_psyche_migration.py::test_kernel_detects_the_migrated_molt_call_shape` |
| `psyche` is on the kernel `summarize` allowlist, and its molt `summary` is domain input rather than that control | `src/lingtai/kernel/tool_result_summary.py:_LTP_V2_MIGRATED_FAMILIES` | `tests/test_tool_family_psyche_migration.py::test_psyche_is_on_the_ltp_v2_summarize_allowlist` |
| The reserved `manual` child returns the canonical result unwrapped; psyche's flat public shape is restored post-dispatch | `src/lingtai/tools/psyche/__init__.py:_adapt_manual_result`, `tool_family/manual.py:build_manual_child` | `tests/test_tool_family_psyche_migration.py::test_manual_child_returns_the_canonical_result_unwrapped`, `::test_manual_public_result_is_flattened_post_dispatch`, `tests/test_intrinsic_manual_actions.py` |
| Identity and pad behavior moved with their families and is claimed there, not here | `src/lingtai/tools/lingtai/CONTRACT.md`, `src/lingtai/tools/pad/CONTRACT.md` | `tests/test_pad_lingtai_split.py`, `tests/test_pad.py`, `tests/test_eigen.py` |
| `context molt` returns the faint-memory result and shed counts | `src/lingtai/tools/psyche/_molt.py:_context_molt` | `tests/test_psyche.py::test_molt_returns_faint_memory` |
| Molt writes a summary file under `system/summaries/` | `src/lingtai/tools/psyche/_snapshots.py:_write_molt_summary` | `tests/test_psyche.py::test_molt_writes_summary_file_for_agent_path` |
| System-forced molt (`context_forget`) still works and writes its own summary | `src/lingtai/tools/psyche/_molt.py:context_forget` | `tests/test_psyche.py::test_context_forget_still_works`, `tests/test_psyche.py::test_context_forget_writes_summary_file_for_system_path` |
| A failed summary write does not block the molt | `src/lingtai/tools/psyche/_molt.py`, `_snapshots.py` | `tests/test_psyche.py::test_summary_write_failure_does_not_block_molt` |
| An unknown action (including the pre-migration flat shape) is rejected before any handler runs | `src/lingtai/tools/psyche/__init__.py:handle` | `tests/test_psyche.py::test_unknown_action_is_rejected`, `tests/test_psyche.py::test_pre_migration_object_action_shape_is_rejected`, `tests/test_tool_family_psyche_migration.py::test_unhashable_or_unknown_action_renders_the_stable_error` |
| True name is set-once while nickname stays mutable | `src/lingtai/tools/psyche/_molt.py:_name_set`/`_name_nickname` | `tests/test_tool_family_psyche_migration.py::test_name_set_is_once_while_nickname_stays_mutable` |
| `manual` mutates no durable state | `src/lingtai/tools/psyche/__init__.py` | `tests/test_tool_family_psyche_migration.py::test_read_only_actions_mutate_no_durable_state` |
| The stop path does not overwrite `system/pad.md` (now a `pad`-family fact) | `src/lingtai/tools/pad/_pad.py` | `tests/test_psyche.py::test_stop_does_not_overwrite_pad_md` |

## Verification matrix

| Invariant | Automated test | Manual check | Risk if broken |
|---|---|---|---|
| The action guard rejects unknowns pre-dispatch | `tests/test_psyche.py::test_unknown_action_is_rejected` | Call `psyche(action='foo', input={})` | Silent no-ops or wrong handler |
| A cross-action `input` never reaches a handler | `tests/test_tool_family_psyche_migration.py::test_wrong_branch_input_is_rejected_before_any_handler_io` | Send `action='name_set'` with `input={'summary': 'x'}` | A mis-paired call shedding context or setting a name |
| Synthesized system molts stay envelope-shaped | `tests/test_tool_family_psyche_migration.py::test_system_forced_molt_synthesizes_the_current_envelope` | Force a molt, read the appended pair's args | History teaching a shape dispatch rejects |
| Pad/lingtai edits reload their prompt sections (now owned by those families) | `tests/test_pad.py::test_pad_edit_then_load`, `tests/test_pad_lingtai_split.py` | Edit pad, inspect prompt sections | Stale identity/notes in prompt |
| Molt archives history and increments count | `tests/test_psyche.py::test_molt_returns_faint_memory` | Molt, inspect `history/` + manifest | Lost history / miscounted molts |
| Molt journal gate refuses without a valid session-journal path | `src/lingtai/tools/psyche/_molt.py:_context_molt` (journal validation) | Molt without `session_journal_path` | Context shed with no durable trail |
| Snapshot/summary write failure is non-fatal | `tests/test_psyche.py::test_summary_write_failure_does_not_block_molt` | Make summaries dir unwritable, molt | A disk hiccup wedges the agent |

Run before merging psyche changes:

```bash
python -m pytest tests/test_psyche.py tests/test_pad.py \
  tests/test_tool_family_psyche_migration.py tests/test_pad_lingtai_split.py \
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

---
name: psyche-contract
tool: psyche
contract_version: 2
related_files:
  - src/lingtai/tools/psyche/__init__.py
  - src/lingtai/tools/psyche/ANATOMY.md
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth — fix the contract in the
  same change and bump contract_version on breaking contract edits.
---

# Psyche capability contract

`psyche` is the bare essentials of agent self: the working `pad`, the
configured-or-self-authored `lingtai` identity, the true `name`/nickname, and
`context_molt` (shed history, keep a briefing). Canonical contract: a closed
root `action` enum plus a strict union of `input` shapes replaces the former
`(object, action)` matrix. Each flattened action name identifies the former
pair (for example `pad_edit` or `lingtai_load`); a bare `load` would collide
between `lingtai` and `pad`. The implementation lives in
`src/lingtai/tools/psyche/`; the code is the source of truth.

## Routing Card

**Use this when:**
- You are editing the pad (`system/pad.md`), the configured-or-self-authored identity
  (`system/lingtai.md` → `character` prompt section), or the true-name/nickname
  handlers.
- You are reviewing the context molt machinery — snapshotting, history archive,
  keep-lists, and the post-molt reminder.

**Do not use this for:**
- Provider-context rebuild after summarizing: that is `system(action=
  'summarize', rebuild=true)` (`src/lingtai/tools/system/CONTRACT.md`). Molt sheds
  *history*; summarize rebuilds the *active context* from pending summaries.
- Notification dismissal (including the post-molt reminder): the reminder is
  dismissed via the `notification` tool (`src/lingtai/tools/notification/CONTRACT.md`).
- Code navigation only: read `src/lingtai/tools/psyche/ANATOMY.md`.

**Fast paths:** the action enum -> §Tool surface; molt/snapshot
paths -> §State & storage.

## Scope

- Canonical tool name: `psyche`.
- Psyche's raw public schema requires only `action` and `input` at root and
  closes every declared object with `additionalProperties: false`; there are no
  flat aliases or coercion. BaseAgent adds public `reasoning` to the model-facing
  envelope, ToolExecutor supplies internal `_reasoning`/`_tc_id`, and the
  system-only `context_forget` path bypasses public dispatch entirely.
- Non-goals: notification verbs, summarize/rebuild, mailbox actions.
- Former name `anima` is not a compatibility alias.
- `reasoning` is never part of psyche's own schema — `BaseAgent._build_tool_schemas`
  injects it into every tool's wire schema, and `ToolExecutor._prepare_args`
  strips it into `_reasoning` before dispatch. Psyche tolerates both the public
  `reasoning` and internal `_reasoning` keys, plus the kernel-injected `_tc_id`,
  at the root alongside `action`/`input` — no other root key is accepted.

## Identity modes

`lingtai` has two supported modes. In forced identity mode, a nonempty resolved
`lingtai` value—inline or loaded from `lingtai_file`—is authoritative and is
materialized into `system/lingtai.md` during boot, refresh, and post-molt prompt
reconstruction. `lingtai_update` still writes and auto-loads
immediately in the current cycle, but the configured forced value replaces it at
the next reconstruction. In self-evolve identity mode, the configured identity
is absent or empty; reconstruction leaves `system/lingtai.md` untouched, so
psyche-authored changes persist across refresh and molt.

## Tool surface

Schema (`src/lingtai/tools/psyche/__init__.py:get_schema`) requires `action`
(closed enum, one compound name per former `(object, action)` pair) and
`input` (an `anyOf` union with one strict, `additionalProperties: false`
shape per action; branch titles are annotations, not JSON-Schema discriminators).
Providers can validate the union shape, while `handle()` correlates the selected
root action with `_ACTION_INPUT_FIELDS[action]` before unwrapping `input` and
calling the flat `_DISPATCH[action]` handler. `handle()` captures a fresh `current_setting` snapshot at call
start, before validation or handler dispatch, and attaches a copy to a copied
result object on every success, error, and `manual` return. The snapshot comes
from the strict versioned, Agent-owned, no-op-placeholder
`settings/psyche.json` (shared `_settings.py` helper); it never changes behavior
and never leaks unknown/secret keys.

| action | Business-required input | Semantic optionals (wire-required nullable keys) | Success output | Error shapes |
|---|---|---|---|---|
| `lingtai_update` | `content` (empty clears) | — | `{status: "ok", path}` | (action/input guard errors) |
| `lingtai_load` | — | — | `{status: "ok", size_bytes, content_preview}` | — |
| `pad_edit` | `content`, `files` (both required nullable keys; at least one non-null) | — | `{status: "ok", path, size_bytes}` | `{error: "Provide content ... files, or both."}`; `{error: "Files not found: ..."}` |
| `pad_load` | — | — | `{status: "ok", path, size_bytes, content_preview, append_*}` | — |
| `pad_append` | `files` (nullable: `null` returns current list, `[]` clears) | — | `{status: "ok", action, files, count}` | `{error: "Files not found: ..."}`; `{error: "Only text files ..."}`; `{error: "Append files total ... token limit ..."}` |
| `context_molt` | `summary`, `session_journal_path` (required non-null strings) | `keep_tool_calls`, `keep_last` (required nullable semantic optionals) | `{status: "ok", note, molt_count, tokens_before/after/shed, kept_*, archive_path, summary_path, session_journal_path}` | `{error: "summary is required ..."}`; journal-validation `{error}`; `{error: "No active chat session to molt."}`; `{error, unmatched_ids}` / `{error, missing_call_ids}` for bad keep-lists; `{error: "keep_last must be ..."}` |
| `name_set` | `content` | — | `{status: "ok", name}` | `{error: "Name cannot be empty..."}`; `{error}` (name already set / immutable) |
| `name_nickname` | `content` (empty clears) | — | `{status: "ok", nickname}` | — |
| `manual` | — (empty object) | — | installed psyche-manual skill body | — |

Table result shapes omit the common `current_setting` field for brevity. Every
success, guard/handler error, and `manual` result carries that copy-safe snapshot;
`append_*` and `kept_*` abbreviate the action-specific metadata named in the
owning implementation and tests.

An unrecognized `action` returns `{error: "Unknown action: ..."}`; `input` not
an object returns `{error: "input must be an object."}`; an input field
outside the action's closed set returns `{error: "Unsupported input
field(s) for <action>: ..."}`; a root key outside
`{action, input, reasoning, _reasoning, _tc_id}` returns `{error:
"Unsupported psyche argument(s): ..."}`. Missing required input fields and
wrong input/root value types are likewise rejected before dispatch. All of these
guards run before any handler and before the legacy per-action business
validation (e.g. the `context_molt` nonempty-summary/journal checks).

Molt's business `input.summary` is a non-empty string, so it cannot satisfy
the executor's exact boolean `input.summary is True` summarization control.
That cross-tool predicate is owned by
`kernel/tool_result_summary.py:summary_requested` and the system result-summary
contract; psyche keeps one focused regression for the collision.

Note: system-forced molt is a separate code path (`context_forget`), invoked by
the kernel on a `.clear` signal, not an agent-callable action. It synthesizes a
schema-exempt internal replay pair. Its `ToolCallBlock.args` data uses canonical
action/input key names plus honest internal provenance:

```text
{
  action: "context_molt",
  input: {
    summary: <system-authored string>,
    session_journal_path: null,
    keep_tool_calls: null,
    keep_last: <actual integer or null>
  },
  _initiator: "system",
  _source: <source>
}
```

This is recorded replay data, not a public `psyche(...)` call; public dispatch
rejects `_initiator` and `_source` and requires a non-null journal path.

## State & storage

All paths are relative to the agent working directory (`agent._working_dir`).

```text
system/pad.md                          — the working pad (pad_edit/pad_load)
system/pad_append.json                 — pinned read-only reference file list
system/lingtai.md                      — self-authored identity → `character` section
system/summaries/molt_<count>_<ts>.md  — molt retrospective (agent- or system-authored)
history/snapshots/snapshot_<count>_<ts>.json — frozen pre-molt ChatInterface substrate
history/chat_history.jsonl             — live chat history (moved on molt)
history/chat_history_archive.jsonl     — appended pre-molt history on each molt
.notification/post-molt.json           — post-molt "resume work" reminder (published on molt)
settings/psyche.json                   — strict versioned no-op settings placeholder (read-only to psyche)
```

- `pad_edit`/`lingtai_update` write their file, then reload the corresponding
  protected prompt section (`pad` / `character`) and flush the system prompt.
- `context_molt` writes a snapshot, wipes the session, increments `molt_count`
  (persisted to `init.json` manifest), archives + unlinks `chat_history.jsonl`,
  replays `keep_last`/`keep_tool_calls` into the fresh session, writes a summary,
  and publishes `.notification/post-molt.json`. Snapshot/summary writes are
  best-effort and never block the molt.
- `settings/psyche.json` is reread fresh on every call (no caching); a
  missing file is the normal placeholder state, and a malformed file is
  reported via `current_setting.settings_error` without changing behavior.

## Cross-platform invariants

- All file access is via `pathlib.Path` (`read_text`/`write_text`,
  `mkdir`, `unlink`) with UTF-8 for text sections; snapshot/summary writes go to
  a `.tmp` sibling then `Path.replace` for atomicity. DOCUMENT.
- Append-file paths may be absolute or workdir-relative (`_resolve_path`);
  binary files are rejected (`_is_text_file` null-byte + UTF-8 check). DOCUMENT.
- No subprocess/PTY; molt operates on in-memory `ChatInterface` objects plus the
  history-file archive. DOCUMENT — no platform-specific behavior; all file access
  via pathlib.

## Anchored claims

| Claim | Source | Test |
|---|---|---|
| `psyche` is a wired intrinsic; `anima` is not an alias | `src/lingtai/tools/psyche/__init__.py` | `tests/test_psyche.py::test_psyche_is_intrinsic`, `tests/test_psyche.py::test_anima_alias_removed`, `tests/test_pad.py::test_psyche_in_all_intrinsics` |
| Schema exposes exactly the closed action enum and its per-action input branch | `src/lingtai/tools/psyche/__init__.py:get_schema`, `_ACTION_INPUT_FIELDS` | `tests/test_psyche.py::test_psyche_schema_has_correct_actions`, `tests/test_psyche.py::test_psyche_schema_input_is_action_keyed_anyof` |
| `lingtai_update` writes `system/lingtai.md` and loads the `character` section | `src/lingtai/tools/psyche/_lingtai.py:_lingtai_update`/`_lingtai_load` | `tests/test_psyche.py::test_lingtai_update_writes_lingtai_md`, `tests/test_psyche.py::test_lingtai_load_writes_character_section` |
| `pad_edit` writes `system/pad.md`; empty content clears; both-null is rejected | `src/lingtai/tools/psyche/_pad.py:_pad_edit` | `tests/test_psyche.py::test_pad_edit_content_only`, `tests/test_psyche.py::test_pad_edit_empty_errors` |
| `pad_edit` imports files and errors on missing paths | `src/lingtai/tools/psyche/_pad.py:_pad_edit` | `tests/test_psyche.py::test_pad_edit_with_files`, `tests/test_psyche.py::test_pad_edit_missing_file_errors` |
| `context_molt` returns the faint-memory result and shed counts | `src/lingtai/tools/psyche/_molt.py:_context_molt` | `tests/test_psyche.py::test_molt_returns_faint_memory` |
| Molt writes a summary file under `system/summaries/` | `src/lingtai/tools/psyche/_snapshots.py:_write_molt_summary` | `tests/test_psyche.py::test_molt_writes_summary_file_for_agent_path` |
| System-forced molt (`context_forget`) still works, uses canonical action+input in its synthesized call, and writes its own summary | `src/lingtai/tools/psyche/_molt.py:context_forget` | `tests/test_psyche.py::test_context_forget_still_works`, `tests/test_psyche.py::test_context_forget_writes_summary_file_for_system_path` |
| A failed summary write does not block the molt | `src/lingtai/tools/psyche/_molt.py`, `_snapshots.py` | `tests/test_psyche.py::test_summary_write_failure_does_not_block_molt` |
| Unknown action / non-object input / unsupported input or root field are rejected before any handler runs | `src/lingtai/tools/psyche/__init__.py:handle` | `tests/test_psyche.py::test_invalid_object`, `tests/test_psyche.py::test_invalid_action_for_object`, `tests/test_psyche.py::test_input_must_be_object`, `tests/test_psyche.py::test_unsupported_input_field_rejected`, `tests/test_psyche.py::test_unsupported_root_field_rejected` |
| The stop path does not overwrite `system/pad.md` | `src/lingtai/tools/psyche/_pad.py` | `tests/test_psyche.py::test_stop_does_not_overwrite_pad_md` |
| Every result carries a fresh, copy-safe, no-op `current_setting` snapshot | `src/lingtai/tools/psyche/__init__.py:handle`, `src/lingtai/tools/_settings.py` | `tests/test_psyche.py::test_current_setting_attached_to_success_result`, `test_current_setting_attached_to_error_result`, `test_current_setting_attached_to_manual_result` |
| A model-smuggled `_initiator` root arg is rejected outright by root-argument validation before the journal gate runs (stronger than pre-migration silent-ignore) | `src/lingtai/tools/psyche/__init__.py:handle` | `tests/test_session_journal_gate.py::test_molt_initiator_system_arg_cannot_bypass_gate` |

## Verification matrix

| Invariant | Automated test | Manual check | Risk if broken |
|---|---|---|---|
| Action/input guard rejects unknowns pre-dispatch | `tests/test_psyche.py::test_invalid_object` / `test_invalid_action_for_object` | Call `psyche(action="foo", input={})` | Silent no-ops or wrong handler |
| Pad/lingtai edits reload their prompt sections | `tests/test_psyche.py::test_lingtai_load_writes_character_section`, `tests/test_pad.py::test_pad_edit_then_load` | Edit pad, inspect prompt sections | Stale identity/notes in prompt |
| Molt archives history and increments count | `tests/test_psyche.py::test_molt_returns_faint_memory` | Molt, inspect `history/` + manifest | Lost history / miscounted molts |
| Molt journal gate refuses without a valid session-journal path | `src/lingtai/tools/psyche/_molt.py:_context_molt` (journal validation) | Molt without `session_journal_path` | Context shed with no durable trail |
| Snapshot/summary write failure is non-fatal | `tests/test_psyche.py::test_summary_write_failure_does_not_block_molt` | Make summaries dir unwritable, molt | A disk hiccup wedges the agent |
| `input.summary` string never triggers a-priori executor summarization | `src/lingtai/kernel/tool_result_summary.py:summary_requested` (exact `is True` check) | N/A — structural, not runtime-observable via psyche alone | A molt's own result would be silently replaced by a lossy LLM summary |

Run before merging psyche changes:

```bash
python -m pytest tests/test_psyche.py tests/test_pad.py tests/test_eigen.py tests/test_session_journal_gate.py -q
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

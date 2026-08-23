---
name: file-contract
tool: file
contract_version: 4
related_files:
  - src/lingtai/tools/file/__init__.py
  - src/lingtai/tools/file/manual/SKILL.md
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/adapters/tool_plugin_host.py
  - src/lingtai/tools/file/_read.py
  - src/lingtai/tools/file/_write.py
  - src/lingtai/tools/file/_edit.py
  - src/lingtai/tools/file/_glob.py
  - src/lingtai/tools/file/_grep.py
  - src/lingtai/tools/file/ANATOMY.md
  - src/lingtai/tools/_file_paths.py
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/services/file_io_sidecar.py
  - src/lingtai/kernel/tool_result_summary.py
  - src/lingtai/intrinsic_skills/read-manual/SKILL.md
  - tests/test_file_tool_family.py
  - tests/test_file_tool_plugin_package.py
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth — fix the contract in the
  same change and bump contract_version on breaking contract edits. This is the
  sole contract for the file surface: it owns the family envelope, the action
  set, the risk posture, the manual promise, AND every per-action input, output,
  cap, and error string. The five pre-migration per-operation contracts were
  folded in here when their packages were deleted; do not recreate them.
---

# File capability contract

`file` is the one public model-facing tool for reading, writing, editing, and
searching the working tree. It is an LTP v2 family (`../CONTRACT.md`) composed
from six canonical children through the generic `ToolFamily` infrastructure.
The implementation lives in `src/lingtai/tools/file/__init__.py`; the code is
the source of truth. `DECLARATION` is a static official host-plugin declaration:
the kernel reserves `file`, the production host grants only `workdir` and
`file_io`, and the registrar — not this package — mounts the bound family.
`FileIOPort` carries precisely File's text read/write/search and runtime-cap
vocabulary; no operation receives a whole Agent or raw service object.

## Routing Card

**Use this when:**
- You are changing the family's public action set, root envelope, or the
  per-action `input` schemas.
- You need the family's risk posture, or the rule that `summarize` must not
  obscure a `write`/`edit` receipt.
- You are editing an operation body, its paging/traversal math, or its exact
  error strings (`_read.py`, `_write.py`, `_edit.py`, `_glob.py`, `_grep.py`).

**Do not use this for:**
- The generic envelope/dispatch machinery: read
  `src/lingtai/tools/tool_family/CONTRACT.md`.
- The underlying byte I/O, sidecar, or traversal budgets:
  `src/lingtai/services/file_io.py` and `file_io_sidecar.py`.

**Fast paths:** action set -> §Scope; root shape -> §Tool surface; per-action
inputs/outputs/errors -> §Per-action behavior; caps and continuation ->
§Per-action behavior > read; risk -> §Risk posture; manual -> §Manual.

## Scope

- Canonical tool name: `file`. This is the only model-facing name; there is no
  `read`, `write`, `edit`, `glob`, or `grep` root.
- Registered via `capabilities=["file"]` only. The five old capability names
  are **not** aliases: `read`, `write`, `edit`, `glob`, and `grep` are unknown
  capability names and fail loudly with the registry's standard unknown-name
  error. `file` is a real capability, not a group.
- Canonical children: `read | write | edit | glob | grep | manual`. Each child
  name is simultaneously the public `action` value and the dispatch key — one
  name, no mapping layer.
- Non-goals: no second summarizer, no family-owned result envelope, no
  settings surface, and no hidden prompt/context lifecycle side effect. In
  particular, `write` and `edit` mutate only the requested durable file: they do
  not reload, recompose, or otherwise mutate the current system prompt. An
  explicit `context.rebuild` (or passive refresh/molt reconstruction) is the
  separate activation boundary for changed prompt sources.

## Tool surface

The composed root is a closed object with exactly four properties — `action`,
`input`, `reasoning`, `summarize` — `additionalProperties: false`, and
`required: ["action", "input", "reasoning"]`. `summarize` is the optional Host
presentation control; `reasoning` is required audit metadata. Neither is ever
passed to an action handler.

Action/input correlation is enforced twice, both generated from the same child
registry:

1. **Schema level** — a root `allOf` of one `if`/`then` per child correlates
   the `action` const with that exact child's `input` schema, and the retained
   `input.oneOf` discloses every action's shape in one place. Both survive to
   the Chat and Responses wires (`llm/openai/adapter.py:_scrub_responses_schema`
   preserves root `oneOf`/`allOf`).
2. **Dispatch** — `ToolFamily.handle` rejects an unknown action, a non-boolean
   `summarize`, an unknown root field, a non-object `input`, and any `input`
   key outside the selected child's own declared schema, all before the
   handler runs.

| Action | Required input | Optional (nullable) input | Result |
|---|---|---|---|
| `read` | `file_path` | `offset`, `limit`, `max_chars` | numbered-line window plus continuation fields |
| `write` | `file_path`, `content` | — | `{status: "ok", path, bytes}` receipt |
| `edit` | `file_path`, `old_string`, `new_string` | `replace_all` | `{status: "ok", replacements}` receipt |
| `glob` | `pattern` | `path` | sorted `matches`, `count`, traversal block |
| `grep` | `pattern` | `path`, `glob`, `max_matches` | `matches`, `count`, `truncated`, traversal block |
| `manual` | — (strict empty) | — | canonical `content`/`structuredContent` manual result |

Optional fields use the provider-compatible nullable representation (declared
`required` and typed `["T", "null"]`). `null` means absent: `_strip_nulls`
translates it away at the family boundary so each operation applies its own
historical defaults — `offset` 1, `limit` 2000, `max_chars` 100 000,
`replace_all` false, `glob` `"*"`, `max_matches` 200, `path` the agent working
directory.

Each child's canonical raw result is returned **verbatim**. The family adds no
outer envelope and no `action` echo, so a `write`/`edit` receipt and every
operation's own `{"status": "error", ...}` dict reach the Host unmodified.
Envelope-level failures are the generic typed `ACTION_REQUIRED` /
`INVALID_ARGUMENT` shapes from `ToolFamily`.

## Per-action behavior

Folded in from the five pre-migration per-operation contracts when their
packages were deleted. Each operation is one self-contained module under
`src/lingtai/tools/file/`; the code is the source of truth. All errors are
plain dicts, never exceptions, so `ToolExecutor`'s `status == "error"` predicate
catches every one of them.

### read (`_read.py`) — read-only

Guarded by: [F001](BEHAVIORS.md#behavior-f001)

Returns `{content, total_lines, lines_shown}`. `content` is `cat -n`-style:
each kept line is `"{lineno}\t{line}"`, preserving the file's own newline style
(`splitlines(keepends=True)`).

Cap constants:

- `DEFAULT_READ_CAP_CHARS = 100_000` — everyday per-call page budget.
- `READ_HARD_CAP_CHARS = PREVENTIVE_MAX_CHARS` — non-configurable ceiling
  (imported from `lingtai.kernel.tool_result_artifacts`).
- The active runtime cap is `min(executor._max_result_chars, READ_HARD_CAP_CHARS)`
  when the executor exposes a positive cap, else `READ_HARD_CAP_CHARS`.
- Per-call `max_chars` is clamped to that runtime cap; invalid values fall back
  to the read default.

When the window is capped mid-way the result also carries
`{truncated: true, cap_chars, returned_chars, requested_offset,
requested_limit, last_returned_line, next_offset, remaining_lines_estimate}`.
When a single line alone exceeds the cap, a bounded prefix is returned with
`line_truncated: true` — `next_offset` then skips to the next physical line and
does **not** recover the hidden tail. Callers resume with
`offset = next_offset` until `truncated` is absent or false.

Errors: `file_path is required`; `File not found: <path>`; the spill-aware
variant "Spill artifact expired: …" when the missing path is under
`tmp/tool-results/` after `..` normalization (a path traversing back out is
*not* misclassified); `Cannot read <path>: <exc>` otherwise.

### write (`_write.py`) — **mutating**

Full-file create-or-overwrite. Parent directories are created by the service.
Success is the receipt `{status: "ok", path, bytes}` where
`bytes = len(content.encode("utf-8"))`.

Errors: `file_path is required`; `content is required`;
`Cannot write <path>: <exc>`.

### edit (`_edit.py`) — **mutating**

Exact string replacement. Success is `{status: "ok", replacements}` —
the full match count when `replace_all`, else `1`.

Errors: `file_path is required`; `old_string is required`;
`new_string is required`; `File not found: <path>`; `Cannot read <path>: <exc>`;
`old_string not found in <path>` (zero matches);
`old_string found <count> times — use replace_all=true or provide more context`
(more than one match without `replace_all`); `Cannot write <path>: <exc>`.
Both the zero-match and the ambiguous-match failures leave the file untouched —
that strictness is the feature that prevents accidental broad changes.

### glob (`_glob.py`) — read-only

Returns `{matches, count}` with the service's sorted match list. When the walk
hit a budget/exclusion limit (`last_traversal.truncated_reason is not None`) the
result also carries `{truncated: true, truncated_reason, traversal: {visited,
elapsed_ms, dirs_pruned}}` so a partial scan is never read as definitive
(issue #164).

Errors: `pattern is required`; `Glob failed: <exc>`.

### grep (`_grep.py`) — read-only

Returns `{matches: [{file, line, text}], count, truncated}`. The tool-facing
names differ from the service kwargs: `glob` and `max_matches` map to the
service's `glob_filter` and `max_results`. Glob values `None`, `""`, or `"*"`
mean "no filter" (`glob_filter=None`); any other value is pushed into the
service so non-matching files are pruned **before** stat/read rather than
post-filtered. `truncated` is true when the already-pruned scan returned at
least `max_matches` results, and is additionally forced true — with
`truncated_reason` and a `traversal` block of `{visited, elapsed_ms,
dirs_pruned, files_skipped_size, files_skipped_binary}` — when the service's
`last_traversal.truncated_reason` is set (issue #164).

Errors: `pattern is required`; `Grep failed: <exc>`.

### Cross-action invariants

- **Path handling:** a relative `file_path`/`path` resolves against the granted
  `WorkdirPort.path` via `resolve_workdir_path`
  (`src/lingtai/tools/_file_paths.py`); absolute paths pass through unchanged to
  preserve the historical error strings.
- **Byte I/O:** every operation reaches the tree only through granted
  `FileIOPort` methods. The Rust search sidecar delegates
  read/write/edit verbatim to `LocalFileIOBackend`; `default_file_io_service`
  selects Rust vs a Python-backed fallback per `LINGTAI_FILE_IO_BACKEND`. The
  operations are backend-agnostic.
- **Encoding:** the service reads and writes text as UTF-8. Non-UTF-8 files are
  handled through `bash` with an explicit encoding, per `file-manual` — the
  operations are not complicated to accommodate them.

## Risk posture

`file` is a **mixed read/write family** and must be declared as such.

- `read`, `grep`, `glob`, and `manual` are read-only.
- `write` and `edit` mutate the working tree.

Per `../CONTRACT.md` invariant 9, a family must not hide a stronger child
action behind a weaker family-level posture. This repository has no ToolGuard,
no MCP-style `annotations`/`readOnlyHint` surface, and no per-tool risk field
at the time of this migration — the enforcement owner is the operation itself
(the injected `FileIOService`) plus the agent workdir boundary, exactly as
before. Should an outer guard or annotation surface be introduced and prove
unable to discriminate per action, the truthful family-level declaration is the
**strongest** child posture — mutating, not read-only. Declaring `file`
read-only because four of six children are would be a false posture.

`summarize` is honored for `file` through the single centralized summarizer
(`kernel/tool_result_summary.py:_LTP_V2_MIGRATED_FAMILIES`); no second
summarizer exists and the raw result is durably recorded before any visible
replacement. Per the shared contract's guidance profiles, `read`, `grep`, and
`glob` are **bulky-result** actions where `summarize=true` is often useful,
while `write` and `edit` are **short-result** actions whose receipts
(`path`/`bytes`, `replacements`) are the entire point of the call: their
receipts must be read exactly, so `summarize` stays false for them. `manual`
likewise stays false so exact procedure is not summarized away.

## Manual

The family owns exactly one manual: `action="manual"` returns the packaged
`tools/file/manual/SKILL.md`, installed at `capabilities/file/SKILL.md` (its
frontmatter remains `name: file-manual`). It performs no target file operation
and touches no path other than the manual's own, and its input is strict empty.
The result is the canonical child shape — full body at `content[0].text`, the
host-local path at `structuredContent.manual_path` — returned without double
wrapping.

`read-manual` remains a **nested parent-owned reference** that `file-manual`
points at for read pagination and truncation depth. It is not a second
top-level manual action and is not reachable as its own `action`.

`file` surfaces no LTP settings file at either the family or action level; the
manual states this explicitly rather than staying silent.

## State & storage

None. The bound `ToolFamily` holds only operation closures over the granted
`WorkdirPort` and `FileIOPort`. All I/O goes through the narrow port; the read
cap's runtime ceiling is observed through that port, never stored.

## Anchored claims

| Claim | Source | Test |
|---|---|---|
| Exactly one public `file` tool; no old roots | `file/__init__.py` (`setup`), `registry.py` | `tests/test_file_tool_family.py::test_only_file_root_is_registered` |
| Root is the closed four-field LTP v2 envelope | `file/__init__.py` (`get_schema`) | `tests/test_file_tool_family.py::test_schema_root_is_closed_action_input_reasoning_summarize` |
| Action const correlates to that child's input schema | `file/__init__.py` (`get_schema`) | `tests/test_file_tool_family.py::test_root_allof_correlates_each_action_to_its_input` |
| Cross-action input is rejected before handler I/O | `tool_family/__init__.py` (`handle`) | `tests/test_file_tool_family.py::test_cross_action_input_is_rejected_before_io` |
| `manual` performs no target I/O and returns body + path | `tool_family/manual.py` | `tests/test_file_tool_family.py::test_manual_performs_no_target_io` |
| Read continuation/`line_truncated` survive migration | `read/__init__.py` (`_apply_cap`) | `tests/test_file_tool_family.py::test_read_continuation_through_family` |
| Write/edit receipts are returned verbatim | `file/__init__.py` (`handle`) | `tests/test_file_tool_family.py::test_write_and_edit_receipts_are_verbatim` |
| Chat and Responses wires keep the correlation | `llm/openai/adapter.py` | `tests/test_file_tool_family.py::test_chat_and_responses_wire_parity` |
| `summarize` is honored and never reaches a handler | `kernel/tool_result_summary.py` | `tests/test_file_tool_family.py::test_summarize_is_recognized_and_stripped` |

## Verification matrix

| Invariant | Automated test | Manual check | Risk if broken |
|---|---|---|---|
| One public root, six actions | `tests/test_file_tool_family.py` | boot an agent, inspect `_tool_handlers` | duplicate/old model roots reappear |
| Envelope closed and correlated | `tests/test_file_tool_family.py` | inspect `get_schema()` | model sends cross-action input |
| Per-operation behavior unchanged | `tests/test_layers_file.py`, `tests/test_read_continuation.py` | read a large file, resume via `next_offset` | silent data loss on long reads |
| Receipts not obscured | `tests/test_file_tool_family.py` | `write` then inspect the raw result | agent cannot confirm a mutation |
| Manual is no-I/O | `tests/test_file_tool_family.py` | call `action="manual"` on a read-only tree | manual becomes a side-effecting call |

Run before merging:

```bash
python -m pytest tests/test_file_tool_family.py tests/test_layers_file.py \
  tests/test_read_continuation.py tests/test_intrinsic_manual_actions.py -q
```

## Schema and glossary ownership

- **Canonical identifiers:** action values, JSON property names, required
  fields, defaults, and bounds are canonical English literals. `get_schema()`
  and `get_description()` are language-independent; the optional `lang`
  argument is accepted for source compatibility but ignored.
- **Glossary resources:** this package owns `glossary-en.md`, `glossary-zh.md`,
  and `glossary-wen.md` for the public family surface. The five retained
  operation packages keep their own glossaries for their internal identifiers.
- **Update triggers:** changing an action value, property name, or the envelope
  requires reviewing all three glossary files in the same PR.
- **Validation:** `python -m lingtai.tools.glossary_validator --check`.

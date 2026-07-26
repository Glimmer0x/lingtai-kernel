---
name: read-contract
tool: read
contract_version: 3
related_files:
  - src/lingtai/tools/read/__init__.py
  - src/lingtai/tools/_file_paths.py
  - src/lingtai/tools/_settings.py
  - src/lingtai/services/file_io_sidecar.py
  - src/lingtai/intrinsic_skills/file-manual/SKILL.md
  - src/lingtai/intrinsic_skills/read-manual/SKILL.md
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth — fix the contract in the
  same change and bump contract_version on breaking contract edits.
---

# Read capability contract

`read` returns numbered, character-capped windows of a single text file. It is a
stateless, read-only wrapper over the injected `FileIOService` (`agent._file_io`).
The implementation lives in `src/lingtai/tools/read/__init__.py`; the code is the
source of truth.

## Routing Card

**Use this when:**
- You are editing the closed action/input schema or its strict dispatch checks.
- You need the exact continuation contract (`truncated`, `next_offset`,
  `line_truncated`) that callers rely on to resume a long read.
- You are reviewing relative path resolution, settings diagnostics, or missing
  file errors.

**Do not use this for:**
- Writing / mutating files: read `src/lingtai/tools/write/CONTRACT.md` or
  `src/lingtai/tools/edit/CONTRACT.md`.
- Recursive discovery / search: read `src/lingtai/tools/glob/CONTRACT.md` or
  `src/lingtai/tools/grep/CONTRACT.md`.
- The underlying byte I/O, sidecar, or traversal budgets: those live in
  `src/lingtai/services/file_io.py` and `file_io_sidecar.py`.

**Fast paths:** tool schema → §Tool surface; cap constants → §Scope; resume /
continuation fields → §Tool surface; settings evidence → §Settings; path &
encoding handling → §Cross-platform invariants.

## Scope

- Canonical tool name: `read`.
- Registered via `capabilities=["read"]` or the `file` sugar
  (`capabilities=["file"]`) which expands to all five file tools.
- Non-goals: no writing, no globbing, no recursive scan, no directory listing,
  no cross-file operations. One file, one window per call.
- Public compatibility with omitted-action or flat arguments is removed.
- Cap constants (source of truth is `src/lingtai/tools/read/__init__.py`):
  - `DEFAULT_READ_CAP_CHARS = 100_000` — everyday per-call page budget.
  - `READ_HARD_CAP_CHARS = PREVENTIVE_MAX_CHARS` — non-configurable ceiling
    (imported from `lingtai.kernel.tool_result_artifacts`).
  - The active runtime cap is `min(executor._max_result_chars, READ_HARD_CAP_CHARS)`
    when the executor exposes a positive cap, else `READ_HARD_CAP_CHARS`.
  - Per-call positive `max_chars` is clamped to that runtime cap; the existing
    source fallback applies when the direct value is absent or not a positive int.

## Tool surface

The raw tool-owned schema is a closed root object containing exactly the required
`action` and required nested `input` fields. `BaseAgent` adds only optional root
`reasoning` to the final model-facing schema. The handler also accepts executor
metadata `_reasoning`; neither metadata field enters the nested read input or
changes read behavior.

`action` is exactly one of `read` or `manual`:

- `read` uses a closed input object requiring `file_path: string` and preserving
  the existing options: `offset: integer` (default `1`, 1-based), `limit:
  integer` (default `2000` lines), `max_chars: integer` (optional per-call
  character budget), and `summary: boolean` (default `false`). No other nested
  field is admitted. The read handler validates declared values before target
  FileIO and does not pass `summary` to FileIO.
- `manual` uses a closed empty input object and returns the real installed
  `read-manual` body and path without attempting a target read.

A nested `summary: true` is a-priori control metadata for `ToolExecutor`: the raw
result is logged before a replacement is generated, and the handler itself still
performs the ordinary read. It never changes offset, limit, cap, path resolution,
or the returned read fields. Summary selection is exact-boolean; root summary
and any compatibility alias are not part of this tool's public contract.

| Call | Required inputs | Success output | Error shapes |
|---|---|---|---|
| `read` | `file_path` | `{content, total_lines, lines_shown}` plus continuation fields when truncated and `current_setting` | plain `{status: "error", message: "...", current_setting}` dict; see below |
| `manual` | empty `input` | installed manual result plus `current_setting` | degraded manual result plus `current_setting` if unavailable |

`content` is `cat -n`-style: each kept line is `"{lineno}\t{line}"`. When the
window is capped mid-way, the extra fields are added:

`{truncated: true, cap_chars, returned_chars, requested_offset, requested_limit,
last_returned_line, next_offset, remaining_lines_estimate}` and, when a single
line alone exceeds the cap, `line_truncated: true` (a bounded prefix of that line
is returned). Callers resume by re-calling with `offset = next_offset`.

## Settings

Every invocation first performs a fresh strict `read_settings(agent, "read")`
read of Agent-owned `settings/read.json`, then attaches a bounded, secret-free
`current_setting` diagnostic to every success, manual, malformed-input, and
FileIO-error result. The exact placeholder schema is only
`{"schema_version": 1}`; it is not a read option and never changes schema,
prompt, path resolution, pagination, cap calculation, manual selection, or
FileIO behavior.

The diagnostic is immutable per invocation and has the shared placeholder shape:
`configurable: false`, `placeholder: "no-op"`, `source`, `settings_revision`,
`settings_hash`, and a `change_hint` naming `settings/read.json`; invalid files
also carry only a bounded `settings_error`. Missing, valid, hot-changed, and
invalid settings are all truthful evidence states. Secrets, settings content,
and absolute host paths are never exposed.

## Error shapes

All public errors are plain dicts, not exceptions, and include `current_setting`:

- `{"status": "error", "message": "read requires root action and input", ...}` —
  missing required root fields.
- `{"status": "error", "message": "file_path is required", ...}` — empty or
  missing path.
- `{"status": "error", "message": "File not found: <path>", ...}` —
  `FileNotFoundError`.
- Spill-aware variant: if the missing path is under `tmp/tool-results/` after
  `..` normalization, the message is the `Spill artifact expired: ...` hint
  instead of the generic not-found string.
- `{"status": "error", "message": "Cannot read <path>: <exc>", ...}` — any
  other target read exception.
- Wrong root/input/action/option types and unknown fields are rejected before
  target FileIO and return the same plain error envelope.

## State & storage

None. `read` is read-only and holds no persistent state. It only reads the target
file through `agent._file_io.read(path)` after settings and validation. The
nested input mapping and metadata fields are not mutated.

## Cross-platform invariants

Do not change any of the following; documented for reviewers only.

- **Path handling:** relative `file_path` is resolved against `agent._working_dir`
  via `resolve_workdir_path` (`src/lingtai/tools/_file_paths.py`); absolute paths pass
  through unchanged to preserve historical error strings.
- **Byte I/O / sidecar:** all target reads go through the injected
  `FileIOService`. The Rust search sidecar delegates read/write/edit verbatim to
  `LocalFileIOBackend`; `default_file_io_service` selects Rust vs. a Python-backed
  fallback per `LINGTAI_FILE_IO_BACKEND` (see
  `src/lingtai/services/file_io_sidecar.py` resolution order). `read` itself is
  backend-agnostic.
- **Encoding:** the service reads text as UTF-8; the source module pins UTF-8
  and parses as Python 3.11.
- **Line splitting:** `content.splitlines(keepends=True)` preserves the file's
  own newline style; `total_lines` counts those lines.

## Anchored claims

| Claim | Source `src/lingtai/tools/read/...` | Test |
|---|---|---|
| Raw schema is closed action/input with strict read/manual branches | `__init__.py` (`get_schema`) | `tests/test_read_action_input.py::test_raw_schema_is_closed_action_input` |
| Agent schema adds only root reasoning metadata | `__init__.py`, BaseAgent schema builder | `tests/test_read_action_input.py::test_agent_schema_has_only_action_input_reasoning_and_real_origin` |
| Provider envelopes preserve action/input/reasoning | BaseAgent schema and provider adapters | `tests/test_read_action_input.py::test_provider_envelopes_keep_public_fields_and_wire_description` |
| Default per-call cap is 100k and hard cap is 200k | `__init__.py` (`DEFAULT_READ_CAP_CHARS`, `READ_HARD_CAP_CHARS`) | `tests/test_read_continuation.py::test_read_cap_default_is_100k_and_hard_cap_is_200k` |
| Handler honors offset/limit/max_chars and continuation fields | `__init__.py` (`handle_read`, `_apply_cap`) | `tests/test_read_action_input.py::test_pagination_max_chars_and_truncation_metadata` |
| `read` reaches targets through the injected FileIOService | `__init__.py` (`handle_read`) | `tests/test_read_action_input.py::test_file_io_delegation_uses_relative_workdir_path` |
| Every public result carries current_setting | `__init__.py` / `_settings.py` | `tests/test_read_action_input.py::test_settings_missing_valid_hot_invalid_and_behavior_prompt_invariance` |
| Manual returns the installed canonical body | `__init__.py` (`load_installed_manual`) | `tests/test_read_action_input.py::test_manual_returns_real_installed_body_and_current_setting` |
| Nested summary control preserves raw-before-replacement ordering | ToolExecutor and `tool_result_summary.py` | `tests/test_read_action_input.py::test_nested_summary_true_serial_uses_actual_handler_and_logs_raw_first` and `::test_nested_summary_true_parallel_reads_replace_after_each_raw_log` |

## Verification matrix

| Invariant | Automated test | Manual check | Risk if broken |
|---|---|---|---|
| Schema has no flat or omitted-action surface | focused read action/input tests | inspect `get_schema()` and an Agent-built schema | model sends rejected legacy shape or aliases leak |
| Continuation fields let callers resume | focused pagination test plus `test_read_continuation.py` | read with a small `max_chars`, re-call with `next_offset` | callers loop or drop tail content |
| Relative paths stay in workdir | focused FileIO test | read a relative path from a known workdir | reads escape / miss the sandbox |
| Errors are dicts and settings remain truthful | focused malformed/settings tests | read a nonexistent path and change settings/read.json | executor crashes or diagnostics lie |
| Reads route through FileIOService | focused delegation test | boot with `capabilities=["read"]` and inspect the injected service | backend selection / sandbox bypassed |
| Summary control is nested and raw is preserved first | focused serial/parallel executor test | use a retained harness with a recording summarizer | raw leaks before replacement or root fallback wins |

Validation uses the repository's no-bytecode compile harness and the glossary
validator; do not substitute a copied schema or manual for the installed
canonical manual.

## Schema and glossary ownership

- **Canonical identifiers:** function names, JSON property names, action/enum
  values, required fields, defaults, and bounds are canonical English literals.
  The schema (`get_schema()`) and description (`get_description()`) are
  language-independent; the optional `lang` argument is accepted for source
  compatibility but ignored.
- **Provider wire:** provider adapters send the global `WIRE_TOOL_DESCRIPTION`
  constant as the top-level tool description; `FunctionSchema.description` holds
  the full canonical prose rendered into `## tools`.
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

---
name: grep-contract
tool: grep
contract_version: 3
related_files:
  - src/lingtai/tools/grep/__init__.py
  - src/lingtai/tools/grep/ANATOMY.md
  - src/lingtai/tools/_file_paths.py
  - src/lingtai/tools/_settings.py
  - src/lingtai/services/file_io.py
  - src/lingtai/services/file_io_sidecar.py
  - src/lingtai/intrinsic_skills/file-manual/SKILL.md
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth; fix both in one change and
  bump contract_version on breaking public edits.
---

# Grep capability contract

`grep` searches file contents by regex under a search root, pushing the basename
`glob` filter into the injected `FileIOService` (`agent._file_io.grep`) so
excluded files are pruned before read. The implementation lives in
`src/lingtai/tools/grep/__init__.py`; the code is the source of truth.

## Routing Card

**Use this when:**
- Editing the closed action/input routing, strict validation, or settings
  diagnostic for the grep wrapper.
- Reviewing glob-filter pass-through or truncation/traversal-stat surfacing.

**Do not use this for:**
- Finding files by name/pattern: read `src/lingtai/tools/glob/CONTRACT.md`.
- Reading one file: read `src/lingtai/tools/read/CONTRACT.md`.
- Regex engine, traversal budgets, or size/binary skips: read
  `src/lingtai/services/file_io.py` / `file_io_sidecar.py`.

**Fast paths:** schema and routing → §Tool surface; settings evidence → §Settings;
match shape and truncation → §Tool surface; FileIO semantics → §Cross-platform
invariants.

## Scope

- Canonical tool name: `grep`.
- Registered via `capabilities=["grep"]` or the `file` sugar.
- Non-goals: no file writes, no filename-only search, and no context lines beyond
  matched lines. Returns `{file, line, text}` records.
- Public compatibility with omitted `action`, omitted `input`, flat arguments, and
  aliases is intentionally removed.

## Tool surface

The raw tool-owned schema is a closed root object with exactly the required root
keys `action` and `input`. `BaseAgent` alone adds optional root `reasoning` to the
model-facing schema; the executor may pass that same metadata to the direct
handler as `_reasoning`. Neither metadata field enters `input` or FileIO.

`action` is exactly one of `grep` and `manual`, and `input` is a closed,
action-specific object:

- **Ordinary:**
  `{"action":"grep","input":{"pattern":"TODO","path":"src","glob":"*.py","max_matches":200,"summary":false},"reasoning":"find pending Python TODOs"}`
  searches under the agent workdir by default. `input.pattern` is a non-empty
  regex string; `input.path` is an optional file/directory root; `input.glob` is
  an optional basename filter defaulting to `"*"`; `input.max_matches` defaults
  to `200`; and nested `input.summary` is an exact-boolean a-priori summary
  control defaulting to `false`.
- **Manual:**
  `{"action":"manual","input":{},"reasoning":"load the installed file guide"}`
  returns the real installed `file-manual` body and path without searching.

The raw schema has no root `reasoning` property; BaseAgent's model-facing schema
adds it without changing the root required list. No flat arguments, omitted
`action`/`input`, unknown keys, compatibility aliases, malformed/non-mapping
payloads, or unhashable action values are accepted. These errors are returned
before target FileIO.

| Call | Required inputs | Optional inputs | Success output | Error shape |
|---|---|---|---|---|
| `grep` | `input.pattern: string` | `input.path: string`, `input.glob: string` (default `"*"`), `input.max_matches: integer` (default `200`), `input.summary: boolean` (default `false`) | `{matches: [{file, line, text}], count, truncated}` plus traversal fields when partial, and `current_setting` | `{status: "error", message: "...", current_setting}` |
| `manual` | empty `input` | none | installed manual result plus `current_setting` | same settings-bearing error envelope if loading fails |

Nested `input.summary=true` is orchestration metadata only. The handler still
performs the ordinary search; `ToolExecutor` logs the raw result first and then
may replace what the model sees with a reasoning-guided summary. It never changes
path, regex, glob filtering, max-match behavior, or returned raw fields. Root
`summary` is not in the canonical schema and is never a summary opt-in.

`glob` values `"*"` and `""` mean no basename filter and are passed to FileIO as
`None`; any other string is passed as `glob_filter`. `truncated` is true when the
service returns at least `max_matches` records, and is also forced true when the
service reports a traversal truncation reason. In the latter case the result
carries `truncated_reason` and `traversal` with `visited`, `elapsed_ms`,
`dirs_pruned`, `files_skipped_size`, and `files_skipped_binary`.

## Settings

Every invocation rereads the strict Agent-owned `settings/grep.json` placeholder
before validating, loading the manual, resolving a path, or calling FileIO. The
only valid file content is the JSON object `{"schema_version": 1}`. This v1
placeholder is metadata-only: it selects no backend, regex mode, filter, cap,
manual, or other behavior. There are no fabricated grep settings or options.

Every success, manual, malformed-input, and FileIO-error result carries a fresh,
secret-free `current_setting` snapshot. It truthfully reports `source` as
`missing`, `settings/grep.json`, or `settings_error`; a bounded
`settings_revision` and `settings_hash`; `configurable: false`, `placeholder:
"no-op"`, and a `change_hint` naming `settings/grep.json`. Invalid files carry
only a bounded `settings_error`; settings contents, secrets, and absolute host
paths are never disclosed. Changing a valid file changes only this diagnostic,
not grep behavior or prompt/schema text.

## Error shapes

All public errors are plain dictionaries, never raised by the handler:

- Missing/empty pattern: `{"status":"error","message":"pattern is required",...}`.
- Wrong root/input/action/field/type: a strict routing/type message with
  `current_setting`; no target FileIO call has occurred.
- Search/path failure: `{"status":"error","message":"Grep failed: <exc>",...}`.

## State & storage

None owned. `grep` is read-only over the filesystem and holds no persistent state.
It reads `agent._file_io.last_traversal` only to surface service statistics and
rereads the Agent-owned settings placeholder per invocation.

## Cross-platform invariants

Do not change these source-truth behaviors:

- **Path handling:** relative `input.path` resolves against `agent._working_dir`
  through `resolve_workdir_path`; absolute roots pass through unchanged. The
  default root is the workdir.
- **FileIO routing:** all searches use the injected `FileIOService`; the optional
  Rust sidecar and Python backend share the public contract.
- **Filter ordering:** non-matching basenames are pruned before stat/read by the
  service; the wrapper does not post-filter results.
- **Encoding/skips:** UTF-8 text is searched; oversized and binary/unreadable
  files are skipped and counted in traversal stats.
- **Ordering and shape:** the service owns match ordering; the wrapper maps each
  result to `{"file": path, "line": line_number, "text": line}` unchanged.

## Anchored claims

| Claim | Source | Focused validation |
|---|---|---|
| Raw schema is closed action/input and has ordinary/manual branches | `__init__.py:get_schema` | `tests/test_grep_action_input.py` |
| BaseAgent adds only root reasoning | `kernel/base_agent/tools.py` + grep schema | focused Agent schema test |
| Provider envelopes preserve named parameters/input_schema | provider adapters + `FunctionSchema` | focused envelope test |
| Description, prompt section, and installed manual show canonical reasoning examples | `get_description`, file manual | focused prompt/manual test |
| Malformed and unhashable calls fail before FileIO | `handle_grep` | strict handler test |
| Real LocalFileIO regex/filter/skip/error semantics remain source-truth | `services/file_io.py` | LocalFileIO focused test |
| Settings are reread, strict, secret-free, and behavior/prompt invariant | `_settings.py`, `handle_grep` | settings focused test |
| Nested summary is raw-first; root summary is rejected/ignored | `tool_result_summary.py`, executor | serial/parallel summary tests |

## Verification matrix

| Invariant | Validation | Risk if broken |
|---|---|---|
| Exact-candidate imports and filenames are used | `sys.path.insert(0, candidate/src)` plus `__file__` assertions | sibling source accidentally tested |
| Provider schema boundaries remain stable | Chat, Responses, Anthropic envelope assertions | provider drift or nested reasoning leak |
| Local search preserves regex/filter/truncation/error behavior | actual `LocalFileIOService` tree and invalid regex calls | incorrect matches or hidden partial results |
| Strict calls do not touch FileIO | recording service and malformed/unhashable inputs | malformed model calls read files |
| Settings missing/valid/hot/invalid are truthful and inert | retained workspaces and sentinel nonleak checks | secret leakage or fabricated behavior |
| Summary semantics are nested, exact, raw-first, and tool-error bypassed | retained serial/parallel executor calls | raw loss, wrong summary, or error masking |

Use direct `unittest` or retained harnesses for this candidate. Do not use pytest,
bytecode compilation, automatic cleanup, or temporary-file lifecycles.

## Schema and glossary ownership

- Canonical identifiers, property names, action values, required fields, and
  defaults are English literals owned by `get_schema()` and this contract.
- Provider adapters preserve named envelopes: Chat uses
  `function.parameters`, Responses uses `parameters`, Anthropic uses
  `input_schema`, and internal `FunctionSchema` uses `parameters`.
- This package owns `glossary-en.md`, `glossary-zh.md`, and `glossary-wen.md`.
  English body remains empty; zh/wen provide concise terminology mappings only.
- The shared installed `file-manual` is the manual returned by grep; grep-owned
  examples in it use canonical nested input and visibly include root reasoning.
- Validate glossary resources with `python -m lingtai.tools.glossary_validator --check`
  when performing the parent validation (without pytest).

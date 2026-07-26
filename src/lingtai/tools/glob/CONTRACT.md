---
name: glob-contract
tool: glob
contract_version: 3
related_files:
  - src/lingtai/tools/glob/__init__.py
  - src/lingtai/tools/_file_paths.py
  - src/lingtai/tools/_settings.py
  - src/lingtai/services/file_io.py
  - src/lingtai/services/file_io_sidecar.py
  - src/lingtai/intrinsic_skills/file-manual/SKILL.md
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth — fix the contract in the
  same change and bump contract_version on breaking contract edits.
---

# Glob capability contract

`glob` finds files matching a pattern under a search root, delegating traversal to
the injected `FileIOService` (`agent._file_io.glob`). The implementation lives in
`src/lingtai/tools/glob/__init__.py`; the code is the source of truth.

## Routing Card

**Use this when:**
- You are editing the glob wrapper's canonical action/input routing or its
  truncation / traversal-stats surfacing (Issue #164 fields).
- You need the exact success shape, settings diagnostic, or partial-result signal.

**Do not use this for:**
- Content search: read `src/lingtai/tools/grep/CONTRACT.md`.
- Reading a specific file: read `src/lingtai/tools/read/CONTRACT.md`.
- Traversal budgets, excluded dirs, or the walker itself: those live in
  `src/lingtai/services/file_io.py` / `file_io_sidecar.py`.

**Fast paths:** tool schema → §Tool surface; partial-result / `truncated`
fields → §Tool surface; path handling → §Cross-platform invariants.

## Scope

- Canonical tool name: `glob`.
- Registered via `capabilities=["glob"]` or the `file` sugar.
- Non-goals: no content search, no file reads, no mutation. It returns a list of
  matching paths and (when the traversal is cut short) budget metadata.

## Tool surface

The raw tool-owned schema is a closed object with exactly the required root keys
`action` and `input`. BaseAgent may add its optional root `reasoning` metadata for
provider calls; the direct handler also accepts executor `_reasoning` metadata.
Neither metadata field is nested into `input` or passed to FileIO.

`action` is exactly one of `glob` and `manual`. The schema exposes two closed
`input` variants: ordinary glob input and the empty manual input object. The
handler validates the selected action against the same closed surface:

- **Ordinary:**
  `{"action": "glob", "input": {"pattern": "**/*.py"}, "reasoning": "discover Python files"}`
  searches under the agent workdir by default. `input.path` may provide a string
  search root; relative roots resolve against the agent workdir and absolute roots
  pass through unchanged. `input.summary` is an optional exact boolean, defaulting
  to `false`; it is accepted as an a-priori summary control but is never sent to
  FileIO and never changes matching. `reasoning` remains Agent-owned root metadata.
- **Manual:** `{"action": "manual", "input": {}, "reasoning": "load the installed file guide"}`
  returns the installed `file-manual` body and path without searching.

The ordinary `input` object requires the non-empty string `pattern`; it may also
contain string `path` and boolean `summary`. The manual `input` object is empty.
Flat-root arguments, omitted action/input, compatibility aliases, unknown keys,
malformed/non-mapping payloads, and unhashable action values are rejected before
FileIO is called. No argument flattening, coercion, or mutation occurs.

| Call | Required inputs | Optional inputs | Success output | Error shapes |
|---|---|---|---|---|
| `glob` | `input.pattern: string` (non-empty) | `input.path: string` (defaults to `agent._working_dir`), `input.summary: boolean` (default false) | `{matches: [...], count, current_setting}` plus traversal fields when the walk was truncated | `{"status":"error", "message":..., "current_setting":...}` |
| `manual` | `input: {}` | none | Installed manual `{status, manual, manual_path, current_setting}` | Same error shape for malformed routing |

When the underlying traversal hit a budget/exclusion limit
(`agent._file_io.last_traversal.truncated_reason is not None`), the glob result
also carries `{truncated: true, truncated_reason, traversal: {visited,
elapsed_ms, dirs_pruned}}` so the model treats partial results as partial, not
definitive. Existing FileIO matching, ignore/error behavior, recursive `**/`
semantics, result ordering, and all result fields are preserved.

Every invocation rereads the strict Agent-owned `settings/glob.json` v1
placeholder through `src/lingtai/tools/_settings.py` before validation, manual
loading, path resolution, or FileIO. Every success, manual, and error result
contains a fresh secret-free `current_setting` snapshot. This placeholder is
metadata-only and cannot select or change glob behavior; missing, valid, hot,
and invalid snapshots are observable only in that diagnostic.

**Error shapes** (plain dicts, not exceptions):
- `{"status": "error", "message": "pattern is required", "current_setting": ...}`
  — missing or empty pattern.
- `{"status": "error", "message": "Glob failed: <exc>", "current_setting": ...}`
  — path resolution or traversal error.
- Routing/type/closed-object errors use the same status/current_setting shape and
  are returned before FileIO.

## State & storage

None owned. `glob` is read-only over the filesystem and holds no persistent state.
It rereads `agent._file_io.last_traversal` (a per-service stats snapshot) only to
surface truncation metadata. The settings placeholder is Agent-owned and is read
fresh for each invocation; glob never writes or interprets it.

## Cross-platform invariants

Do not change any of the following; documented for reviewers only.

- **Path handling:** relative `input.path` (search root) is resolved against
  `agent._working_dir` via `resolve_workdir_path` (`src/lingtai/tools/_file_paths.py`);
  absolute roots pass through unchanged. The default root is the workdir.
- **Sidecar resolution:** recursive `glob` is one of the two operations routed
  through the Rust search sidecar when present; `default_file_io_service`
  autodiscovers a packaged/dev-tree binary and soft-falls back to the Python
  backend (see `src/lingtai/services/file_io_sidecar.py` resolution order). Both
  backends share traversal defaults so results stay in lock-step.
- **Encoding:** returned matches are string paths.
- **Ordering:** the FileIO service owns the source-truth sorted result list; the
  wrapper delegates it unchanged.
- **Summary isolation:** `input.summary` is an orchestration control only; it is
  not a FileIO option and is not included in the matching call.

## Anchored claims

| Claim | Source `src/lingtai/tools/glob/...` | Test |
|---|---|---|
| Canonical action/input routing is closed | `__init__.py` (`get_schema`, `handle_glob`) | `tests/test_glob_action_input.py` |
| Glob returns matching files through the capability | `__init__.py` (`handle_glob`) | `tests/test_glob_action_input.py` |
| Glob failures return a `{status: error}` dict with settings evidence | `__init__.py` (`handle_glob`) | `tests/test_glob_action_input.py` |
| Relative search roots resolve under the workdir | `__init__.py` (`resolve_workdir_path`) | `tests/test_glob_action_input.py` |
| Glob routes through the injected FileIOService | `__init__.py` (`handle_glob`) | `tests/test_glob_action_input.py` |
| Default-excluded dirs are skipped by the service glob | `src/lingtai/services/file_io.py` | `tests/test_glob_action_input.py` |
| Installed manual body/path is returned | `__init__.py` (`load_installed_manual`) | `tests/test_glob_action_input.py` |

## Verification matrix

| Invariant | Automated test | Manual check | Risk if broken |
|---|---|---|---|
| Raw and BaseAgent schemas expose canonical closed action/input shape | `tests/test_glob_action_input.py` | Inspect raw and actual Agent schema | Flat or ambiguous provider calls |
| Provider envelopes remain unchanged | `tests/test_glob_action_input.py` | Inspect Chat/Responses/Anthropic tools | Provider drift |
| Pattern matching, sorting, recursion, and exclusions remain source-truth | `tests/test_glob_action_input.py` | `glob` `**/*.py` under a known tree | Missed or spurious matches |
| Truncated walks are flagged | `tests/test_glob_action_input.py` | `glob` a budgeted tree, confirm `truncated` set | Partial results mistaken for complete |
| Errors are dicts, not exceptions | `tests/test_glob_action_input.py` | Malformed action/input and an invalid root | Executor crash instead of message |
| Settings are reread and behavior-inert | `tests/test_glob_action_input.py` | Change settings between calls | Settings accidentally select behavior |
| Nested summary is raw-first and root summary is ignored | `tests/test_glob_action_input.py` | Serial and parallel executor calls | Raw result lost or wrong summary mode |

Run the dedicated module through the repository's normal test runner when the
parent agent performs test validation. This task's validation harnesses use
in-memory `compile()` and retained direct Python calls rather than pytest.

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

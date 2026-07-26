---
name: edit-contract
tool: edit
contract_version: 3
related_files:
  - src/lingtai/tools/edit/__init__.py
  - src/lingtai/tools/_file_paths.py
  - src/lingtai/tools/_settings.py
  - src/lingtai/services/file_io_sidecar.py
  - src/lingtai/intrinsic_skills/file-manual/SKILL.md
maintenance: |
  Keep related_files as repo-relative paths to real files. If behavior and this
  contract disagree, the code is the source of truth — fix the contract in the
  same change and bump contract_version on breaking contract edits.
---

# Edit capability contract

`edit` performs exact string replacement in a single existing file. It reads the
file through the injected `FileIOService` (`agent._file_io`), replaces
`old_string` with `new_string`, and writes the result back. The implementation
lives in `src/lingtai/tools/edit/__init__.py`; the code is the source of truth.

## Routing Card

**Use this when:**
- You are editing the action/input schema or its strict root/branch validation.
- You need the exact ambiguity rule (what happens when `old_string` appears more
  than once) or the `replace_all` rule.
- You need the per-call settings diagnostic contract.

**Do not use this for:**
- Full-file replacement or new files: read `src/lingtai/tools/write/CONTRACT.md`.
- Reading content: read `src/lingtai/tools/read/CONTRACT.md`.
- The byte-level read/write: `src/lingtai/services/file_io.py`.

**Fast paths:** tool schema → §Tool surface; ambiguity / `replace_all` rule →
§Tool surface; read-then-write flow → §State & storage.

## Scope

- Canonical tool name: `edit`.
- Registered via `capabilities=["edit"]` or the `file` sugar.
- Non-goals: no regex, no fuzzy matching, no multi-file edits, no file creation
  (the target must already exist). Matching is literal substring counting via
  `str.count` / `str.replace`.
- Public compatibility with omitted-action or flat arguments is removed.

## Tool surface

The raw tool-owned schema is a closed root object with required `action` and
required nested `input`, and no other root fields. `BaseAgent` adds optional root
`reasoning` only to the model-facing schema. The handler also accepts executor
metadata `_reasoning`; neither metadata field enters action dispatch.

`action` is exactly one of `edit` or `manual`:

- `edit` uses a closed input object requiring `file_path: string`,
  `old_string: string`, `new_string: string`, and `replace_all: boolean | null`.
  Strict providers therefore always send `replace_all`; `null` means false.
  Direct handler calls that omit it also preserve the historical false default.
- `manual` uses a closed empty input object and returns the real installed
  `file-manual` body without attempting an edit.

| Call | Required inputs | Success output | Error shapes |
|---|---|---|---|
| `edit` | `file_path`, `old_string`, `new_string`, `replace_all` (nullable boolean) | `{status: "ok", replacements}` (`count` when true, else `1`) | plain `{status: "error", message: "...", current_setting}` dict; see below |
| `manual` | empty `input` | installed manual result plus `current_setting` | degraded manual result plus `current_setting` if unavailable |

Every result, including malformed, unknown-action, manual, and file-I/O results,
contains `current_setting`. The first operation of every call is a strict fresh
`read_settings(agent, "edit")`. The Agent-owned settings placeholder accepts
only `{schema_version: 1}`; missing, valid, hot-changed, or invalid settings
produce evidence only and never change path resolution, matching, counts,
ambiguity, replacement, or FileIO behavior.

**Error shapes** (plain dicts, not exceptions):
- `{"status": "error", "message": "edit requires root action and input", ...}` —
  missing required root fields.
- `{"status": "error", "message": "file_path is required", ...}` — empty/missing path.
- `{"status": "error", "message": "File not found: <path>", ...}` —
  `FileNotFoundError` on the initial read.
- `{"status": "error", "message": "Cannot read <path>: <exc>", ...}` — other read failure.
- `{"status": "error", "message": "old_string not found in <path>", ...}` — zero matches.
- `{"status": "error", "message": "old_string found <count> times — use replace_all=true or provide more context", ...}` — more than one match without `replace_all`.
- `{"status": "error", "message": "Cannot write <path>: <exc>", ...}` — write-back failure.

## State & storage

None owned. `edit` does its own read→replace→write against the target file via
`agent._file_io.read` then `agent._file_io.write`; it holds no persistent state.
When `replace_all` is false (including null or direct omission), the replacement
is `content.replace(old, new, 1)`; when true it replaces every occurrence.

## Cross-platform invariants

Do not change any of the following; documented for reviewers only.

- **Path handling:** relative `file_path` is resolved against `agent._working_dir`
  via `resolve_workdir_path` (`src/lingtai/tools/_file_paths.py`); absolute paths pass
  through unchanged.
- **Byte I/O / sidecar:** both the read and the write-back go through the injected
  `FileIOService`; the Rust sidecar delegates read/write/edit verbatim to
  `LocalFileIOBackend` (see `src/lingtai/services/file_io_sidecar.py`).
- **Encoding / matching:** matching is on the UTF-8 decoded text; substring
  counting is exact and newline-sensitive (no normalization).

## Anchored claims

| Claim | Source `src/lingtai/tools/edit/...` | Test |
|---|---|---|
| Raw schema is closed action/input with strict edit/manual branches | `__init__.py` (`get_schema`) | `tests/test_edit_capability.py::test_raw_schema_is_closed_action_input` |
| Agent schema adds only root reasoning metadata | `__init__.py`, BaseAgent schema builder | `tests/test_edit_capability.py::test_agent_schema_has_only_action_input_reasoning` |
| Exact replacement and legacy false defaults work only under explicit edit action | `__init__.py` (`handle_edit`) | `tests/test_edit_capability.py::test_edit_replacement_and_defaults` |
| Manual returns installed canonical body | `__init__.py` (`load_installed_manual`) | `tests/test_edit_capability.py::test_manual_returns_installed_body` |
| Settings are fresh evidence and behavior-invariant | `__init__.py` / `_settings.py` | `tests/test_edit_capability.py::test_settings_are_attached_and_invariant` |
| Envelope schemas expose only action/input/reasoning | BaseAgent schema and provider adapters | `tests/test_edit_capability.py::test_provider_envelopes_keep_public_fields` |

## Verification matrix

| Invariant | Automated test | Manual check | Risk if broken |
|---|---|---|---|
| Single replacement round-trips | `tests/test_edit_capability.py::test_edit_replacement_and_defaults` | edit a unique substring, then read the result | Silent corruption / wrong content |
| Ambiguous match is refused without `replace_all` | `__init__.py` count guard | edit a substring that appears twice without `replace_all` | Unintended mass replacement |
| Missing file / missing substring reported clearly | `__init__.py` structured errors | edit a nonexistent file or absent substring | Executor crash or silent no-op |
| Relative paths stay in workdir | `__init__.py` `resolve_workdir_path` | edit a relative path from a known workdir | Edits escape the sandbox |
| Edit routes through FileIOService | `__init__.py` (`handle_edit`) | boot with `capabilities=["edit"]` and inspect the injected service | Backend selection / sandbox bypassed |
| Settings never select behavior | `_settings.py` plus handler | repeat after missing/valid/hot/invalid settings changes | Configuration leaks into edits |

Validation uses the repository's no-bytecode compile harness and the glossary
validator; do not substitute a schema or manual copy for the installed canonical
manual.

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

---
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/grep/__init__.py
  - src/lingtai/tools/grep/CONTRACT.md
  - src/lingtai/tools/grep/glossary-en.md
  - src/lingtai/tools/grep/glossary-zh.md
  - src/lingtai/tools/grep/glossary-wen.md
  - src/lingtai/tools/_file_paths.py
  - src/lingtai/tools/_manual.py
  - src/lingtai/tools/_settings.py
  - src/lingtai/services/file_io.py
  - src/lingtai/intrinsic_skills/file-manual/SKILL.md
  - tests/test_grep_action_input.py
maintenance: |
  Keep related_files as repo-relative paths to real files and keep this anatomy
  connected to src/lingtai/tools/ANATOMY.md. The public grep schema and examples
  are canonical action/input calls; do not reintroduce flat or omitted-action
  compatibility. If source and anatomy drift, report and repair both.
---
# src/lingtai/tools/grep/

The public `grep` capability searches text by regular expression through the
injected `FileIOService`. Its migration-owned surface is a closed root object
with required `action` and `input`; `BaseAgent` adds only optional root
`reasoning` for model-facing calls.

## Components

- `__init__.py` — owns `get_schema`, `get_description`, registration, strict
  action/input validation, manual dispatch, settings evidence, FileIO mapping,
  and traversal-stat projection.
- `CONTRACT.md` — canonical public contract, provider envelope boundaries,
  settings placeholder evidence, and verification matrix.
- `glossary-*.md` — concise terminology resources; English remains empty and
  localized bodies name canonical identifiers only.
- `intrinsic_skills/file-manual/SKILL.md` — installed shared file guide; grep
  examples use `action`, nested `input`, and visible Agent-injected `reasoning`.

## Public shape

Ordinary calls use
`{"action":"grep","input":{"pattern":"...","path":"...","glob":"*.py","max_matches":200,"summary":false},"reasoning":"..."}`.
Manual calls use
`{"action":"manual","input":{},"reasoning":"..."}`. `input.summary` is
an exact-boolean orchestration hint consumed by `ToolExecutor`, not a FileIO
setting. Flat fields, omitted action/input, unknown keys, and root summary are
not public grep compatibility.

## Connections and invariants

`setup()` registers the handler on `Agent`; relative input paths resolve against
`agent._working_dir`. `LocalFileIOService.grep` owns regex matching, basename
glob pruning before reads, traversal budgets, size/binary skips, and match
ordering. `read_settings` rereads only the Agent-owned v1 no-op placeholder and
`current_setting` reports bounded secret-free evidence; it never supplies grep
behavior. Provider adapters preserve named schema envelopes: Chat
`function.parameters`, Responses `parameters`, Anthropic `input_schema`, and
internal `FunctionSchema.parameters`.

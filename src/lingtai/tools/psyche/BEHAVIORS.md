---
name: psyche-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/psyche/CONTRACT.md
  - src/lingtai/tools/psyche/ANATOMY.md
  - src/lingtai/tools/psyche/__init__.py
  - src/lingtai/tools/psyche/glossary-en.md
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  psyche behavior clause changes, update the guarding LABT here in the same
  change.
---
# Psyche Tool Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/psyche/CONTRACT.md` (every action read-only; durable changes
via file + explicit rebuild). Pinned pytest commands must run from the repo
root with the project's Python.

## Behavior PY001 — every psyche action is read-only and durable changes apply only through file + an explicit rebuild

- **id**: PY001
- **title**: every psyche action is read-only and durable changes apply only through file + an explicit rebuild
- **guards**: `psyche-tool-contract` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>`
- **estimate**: ≈ 15 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_psyche_family.py -q` and capture the outcome.
2. Call every `psyche` action with its strict input on `<scratch>` and hash all prompt/source files before and after; record the results.
3. Make a durable change with `file.edit` on the domain's own source and confirm the prompt section does not change until one explicit `context(action="rebuild", input={}, reasoning="...")` (or passive refresh/molt) is applied.

### Expected evidence
- [ ] Step 1: the psyche family suite passes, pinning five-domain manual routing and read-only behavior.
- [ ] Step 2: no `psyche` action authors, edits, pins, installs, migrates, rescans a catalog, writes a prompt/source file, or reloads prompt state — all file hashes are unchanged.
- [ ] Step 3: file mutation never hot-loads the prompt; the prompt section updates only after an explicit rebuild or passive reconstruction.

### Pass / Fail
Pass when the suite passes and the read-only/no-hot-load observations hold. Fail on any mutating `psyche` action or on a prompt that reloads from a plain file edit; record the evidence trail in the task report.

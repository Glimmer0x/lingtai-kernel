---
name: lingtai-tool-protocol-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/_catalog.py
  - src/lingtai/tools/_manual.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when an LTP
  envelope or settings rule changes, update the guarding LABT here in the same
  change.
---
# LingTai Tool Protocol (LTP) Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/CONTRACT.md` (closed root envelope, strict per-action input,
manual action, two-level settings). Pinned pytest commands must run from the
repo root with the project's Python.

## Behavior LP001 — a migrated family's model-facing root is exactly action/input/reasoning/summarize and closed

- **id**: LP001
- **title**: a migrated family's model-facing root is exactly action/input/reasoning/summarize and closed
- **guards**: `lingtai-tool-protocol` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; one migrated family to probe (e.g. `file`, `knowledge`, or `mcp`)
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_tool_family_wire_parity.py -q` and capture the outcome.
2. Fetch a migrated family's advertised schema (`get_schema()` on the family) and verify the root properties are exactly `action`, `input`, `reasoning`, and `summarize` with `additionalProperties: false`, and that `reasoning`/`summarize` never appear nested under `input`.
3. Confirm `ToolExecutor` strips root `summarize` before handler dispatch and that the root boolean survives through result post-processing on both single and parallel call paths.

### Expected evidence
- [ ] Step 1: the wire-parity suite passes, pinning envelope correlation on both Chat Completions and Responses wires.
- [ ] Step 2: the schema's root is closed with exactly the four properties; no `parameters`/`payload` alias appears; action branches are closed per action.
- [ ] Step 3: `_reasoning` never appears in the model-facing schema or nested `input`; raw output is durably recorded before any visible summary replacement, and tool errors stay exact and unmodified.

### Pass / Fail
Pass when the suite passes and the closed-envelope observation holds for a real migrated family. Fail on an extra root property, on `reasoning`/`summarize` leaking into `input`, or on a summary replacing the recorded raw output; record the evidence trail in the task report.

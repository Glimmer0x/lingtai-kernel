---
name: task-card-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/task_card/CONTRACT.md
  - src/lingtai/tools/task_card/ANATOMY.md
  - src/lingtai/tools/task_card/__init__.py
  - src/lingtai/mcp_servers/task_card/resident.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  task-card behavior clause changes, update the guarding LABT here in the same
  change.
---
# Intrinsic Task Card Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/task_card/CONTRACT.md` (start writes body then exact active,
second start fails closed, stop/remove semantics, watch persistence). Pinned
pytest commands must run from the repo root with the project's Python.

## Behavior TK001 — start writes the body atomically before exact active, and a second start fails closed

- **id**: TK001
- **title**: start writes the body atomically before exact active, and a second start fails closed
- **guards**: `intrinsic-task-card` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>` with a renderer script inside it
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_task_card_controller.py tests/test_task_card_resident_shared.py -q` and capture the outcome.
2. In `<scratch>`, start a watch with a renderer that prints a body; verify `taskcard/taskcard.md` is written atomically before `taskcard/status` becomes exact `active`, and that `taskcard/watch.json` is persisted.
3. Start a second watch while the first is active and record the result; then call `remove` twice and record both results.

### Expected evidence
- [ ] Step 1: the task-card controller and resident suites pass, pinning route/slot, old-first rotation, peer adoption, and failure-state transitions.
- [ ] Step 2: the body file precedes the exact-`active` status write; the watch descriptor survives for restart resume; renderer failures preserve the last valid body and emit deduped `task_card.error`/`recovered` notifications.
- [ ] Step 3: a second `start` fails closed (at most one active watch per agent); `remove` retires the watch first (writes `inactive`, joins the updater), then deletes the body; a repeated `remove` is idempotent and never an error.

### Pass / Fail
Pass when the suites pass and the ordering/idempotency observations hold. Fail on `active` before the body write, on a second concurrent watch, or on a non-idempotent `remove`; record the evidence trail in the task report.

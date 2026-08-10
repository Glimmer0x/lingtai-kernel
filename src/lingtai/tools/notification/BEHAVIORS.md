---
name: notification-tool-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/notification/CONTRACT.md
  - src/lingtai/tools/notification/ANATOMY.md
  - src/lingtai/tools/notification/__init__.py
  - src/lingtai/tools/notification/schema.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  notification tool behavior clause changes, update the guarding LABT here in
  the same change.
---
# Notification Tool Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/notification/CONTRACT.md` (manual read-only, check/current
state, narrow dismiss actions, Store semantics preserved). Pinned pytest
commands must run from the repo root with the project's Python.

## Behavior NT001 — manual stays read-only and check reports current notification state without mutating producer state

- **id**: NT001
- **title**: manual stays read-only and check reports current notification state without mutating producer state
- **guards**: `notification-tool` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>` with a populated `.notification/`
- **estimate**: ≈ 15 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_notification_tool.py -q` and capture the outcome.
2. Call `notification(action="manual", input={}, reasoning="probe")` and record the result; hash `.notification/` before and after.
3. Call `notification(action="check", input={}, reasoning="probe")` and confirm it reports current channel state; then perform a narrow dismiss and confirm producer canonical state is untouched.

### Expected evidence
- [ ] Step 1: the notification-tool suite passes, pinning the eight operational actions, Store semantics, and notification Core guards.
- [ ] Step 2: `manual` returns the installed per-agent guidance and performs no check/dismiss state change — `.notification/` is byte-identical.
- [ ] Step 3: `check` reports current state without mutating it; dismissal is producer-specific or atomic and never rewrites producer canonical state; no `system` notification/dismiss alias exists.

### Pass / Fail
Pass when the suite passes and the read-only manual/check observations hold. Fail on a mutating `manual`, on `check` changing state, or on generic dismissal corrupting producer canonical state; record the evidence trail in the task report.

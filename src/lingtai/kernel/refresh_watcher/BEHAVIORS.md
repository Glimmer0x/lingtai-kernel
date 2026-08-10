---
name: refresh-watcher-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/kernel/refresh_watcher/CONTRACT.md
  - src/lingtai/kernel/refresh_watcher/ANATOMY.md
  - src/lingtai/kernel/refresh_watcher/__init__.py
  - src/lingtai/kernel/refresh_watcher/watcher_program.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  refresh-watcher behavior clause changes, update the guarding LABT here in the
  same change.
---
# Refresh Watcher Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/kernel/refresh_watcher/CONTRACT.md` (one detached watcher spawn per
refresh, frozen request, handshake normalization, env-overwrite policy). Pinned
pytest commands must run from the repo root with the project's Python.

## Behavior RW001 — a successful refresh spawns the detached watcher exactly once, and failed ACK setup does not spawn

- **id**: RW001
- **title**: a successful refresh spawns the detached watcher exactly once, and failed ACK setup does not spawn
- **guards**: `refresh-watcher` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>`
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_perform_refresh_handshake.py -q` and capture the outcome.
2. Run `python -m pytest tests/test_refresh_watcher_process.py -q` and capture the outcome.
3. In `<scratch>`, drive one `_perform_refresh` and count detached watcher spawns (via the injected `RefreshWatcherPort` fake); verify the frozen request carries only handshake paths, working directory, tuple command, identity fields JSON, and the env-overwrite policy bit.

### Expected evidence
- [ ] Step 1: the refresh handshake suite passes (`.refresh` → `.refresh.taken`, exactly one spawn, cancellation/shutdown path).
- [ ] Step 2: the watcher process suite passes (rendered policy, exact copied environment, detached stdio, platform detached handoff).
- [ ] Step 3: exactly one `spawn_detached` call per successful refresh; a failed ACK setup performs zero spawns; the request carries no generated source and no caller environment.

### Pass / Fail
Pass when the suites pass and the one-spawn/zero-spawn observations hold. Fail on a second spawn, on a spawn after failed ACK setup, or on a request that carries generated source or caller environment; record the evidence trail in the task report.

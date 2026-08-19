---
name: refresh-watcher-behavior-tests
behavior_version: 2
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/kernel/refresh_watcher/CONTRACT.md
  - src/lingtai/kernel/refresh_watcher/ANATOMY.md
  - src/lingtai/kernel/refresh_watcher/__init__.py
  - src/lingtai/kernel/refresh_watcher/watcher_program.py
  - tests/test_perform_refresh_handshake.py
  - tests/test_refresh_watcher_process.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  refresh-watcher behavior clause changes, update the guarding LABT here in the
  same change.
---
# Refresh Watcher Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/kernel/refresh_watcher/CONTRACT.md` (one detached watcher spawn per
refresh, frozen request, handshake normalization, env-overwrite policy, and the
bounded relaunch health-check/duplicate-exit waits). Pinned pytest commands must
run from the repo root with the project's Python.

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

## Behavior RW002 — a slow-booting relaunch is not declared dead, and a terminated duplicate is gone before the next attempt

- **id**: RW002
- **title**: a slow-booting relaunch is not declared dead, and a terminated duplicate is gone before the next attempt
- **guards**: `refresh-watcher` § Contract rules, rule 2
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>`
- **estimate**: ≈ 25 minutes
- **motivation**: production incident 2026-08-19 (`spiritual-bliss-attractor/.lingtai/codex`) exhausted all 12 relaunch attempts. The health check slept `HEALTH_CHECK_WAIT` once and sampled `.agent.heartbeat` a single time — too early for an agent still spawning MCP stdio servers — and the loop retried immediately after SIGKILLing a duplicate that had not yet released the working directory, so every attempt collided again with `another lingtai agent is already running`.

### Steps
1. From `<repo>`, run `python -m pytest tests/test_refresh_watcher_process.py tests/test_perform_refresh_handshake.py -q` and capture the outcome.
2. Read the rendered policy (`render_watcher_script`) and confirm the post-relaunch health check is a bounded poll (`_await_fresh_heartbeat`, `HEALTH_CHECK_BUDGET`, `WATCHER_POLL_INTERVAL`) rather than one `time.sleep(HEALTH_CHECK_WAIT)` followed by a single heartbeat read.
3. In `<scratch>`, run the rendered policy against a fake `PROCESS_MECHANISM` whose relaunch writes its first `.agent.heartbeat` later than `HEALTH_CHECK_WAIT` but inside `HEALTH_CHECK_BUDGET`; record the launch count and the `refresh_watcher_success` event.
4. In `<scratch>`, run the rendered policy against a fake whose duplicate only leaves the process table some time after `force_stop`; record the timestamp of each `start_agent` call and of the duplicate's disappearance.
5. In `<scratch>`, run the rendered policy against a fake whose duplicate never dies; record `logs/refresh_failed_permanent.json` and the emitted event types.

### Expected evidence
- [ ] Step 1: both suites pass.
- [ ] Step 2: the rendered policy contains `_await_fresh_heartbeat` bounded by `HEALTH_CHECK_BUDGET`, `_await_duplicate_exit` bounded by `DUPLICATE_EXIT_WAIT`, and no single-sample `time.time() - hb_ts < HEALTH_CHECK_WAIT + 10` health check.
- [ ] Step 3: exactly one `start_agent` call, exit code 0, and one `refresh_watcher_success` event whose `heartbeat_wait` exceeds `HEALTH_CHECK_WAIT`.
- [ ] Step 4: the second `start_agent` call happens no earlier than the duplicate's disappearance, and no `refresh_watcher_stale_duplicate_still_alive` event is emitted.
- [ ] Step 5: the loop terminates after `MAX_ATTEMPTS`; the artifact records `last_cleanup_action = 'terminate_stale_duplicate'` and `last_cleanup_result = 'still_alive'`; one `refresh_watcher_stale_duplicate_still_alive` event per attempt; the final event is `refresh_failed_permanent`.

### Pass / Fail
Pass when a heartbeat that arrives after `HEALTH_CHECK_WAIT` but inside `HEALTH_CHECK_BUDGET` is accepted on the first attempt, the retry waits for a terminated duplicate, and an undying duplicate is reported honestly instead of hanging. Fail on a slow boot costing a second attempt, on a retry that starts while the duplicate still matches the same-agent guard, on an unbounded wait, or on a terminal artifact that hides the `still_alive` outcome; record the evidence trail in the task report.

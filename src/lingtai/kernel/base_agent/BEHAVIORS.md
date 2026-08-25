---
name: base-agent-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/kernel/base_agent/CONTRACT.md
  - src/lingtai/kernel/base_agent/ANATOMY.md
  - src/lingtai/kernel/base_agent/lifecycle.py
  - src/lingtai/kernel/base_agent/turn.py
  - tests/test_perform_refresh_handshake.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a
  composed-lifecycle behavior clause of the agent-runtime contract changes,
  update the guarding LABT here in the same change.
---
# Agent Runtime Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/kernel/base_agent/CONTRACT.md` (the composed lifecycle promise:
construction, liveness, ordered stop, refresh handshake). Pinned pytest commands
must run from the repo root with the project's Python.

## Behavior BA001 — stop is ordered manifest-persist → heartbeat-withdraw → lease-release, and liveness is presence-plus-heartbeat, never process visibility

- **id**: BA001
- **title**: stop is ordered manifest-persist → heartbeat-withdraw → lease-release, and liveness is presence-plus-heartbeat, never process visibility
- **guards**: `agent-runtime` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; no other agent process sharing the scratch working directory
- **estimate**: ≈ 20 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_lifecycle_daemon_shutdown.py -q` and capture the outcome.
2. Run `python -m pytest tests/test_agent.py -q` and capture the outcome.
3. Inspect `src/lingtai/kernel/base_agent/lifecycle.py` teardown and confirm the artifact order manifest-persist → heartbeat-withdraw → lease-release is preserved on the best-effort error path.

### Expected evidence
- [ ] Step 1: the lifecycle shutdown suite passes, pinning heartbeat-before-release ordering and manifest persistence through teardown.
- [ ] Step 2: the agent construction/start/stop suite passes, pinning construction, liveness, and stop behavior.
- [ ] Step 3: the ordered teardown matches the contract's `agent-runtime.stop.v1` clause; no step reorders heartbeat withdrawal before the final manifest write.

### Pass / Fail
Pass when both suites pass and the teardown order matches the contract. Fail on any reordering, on heartbeat freshness lost before teardown completes, or on liveness being derived from process visibility; record the evidence trail in the task report.

## Behavior BA002 — a refresh that fails before the watcher handoff can be retried in the same process, and only a completed handoff is terminal

- **id**: BA002
- **title**: a refresh that fails before the watcher handoff can be retried in the same process, and only a completed handoff is terminal
- **guards**: `agent-runtime` § Contract rules, rule 5 (`agent-runtime.refresh.v1`) — see [CONTRACT.md](CONTRACT.md#contract-rules)
- **supersedes**: `tests/test_perform_refresh_handshake.py::test_launch_cmd_exception_releases_single_flight_slot_for_retry`, `tests/test_perform_refresh_handshake.py::test_raising_spawn_releases_slot_without_shutdown_and_retry_is_not_coalesced`, `tests/test_perform_refresh_handshake.py::test_successful_handoff_keeps_slot_claimed_even_if_post_handoff_logging_raises` (kept as bottom asserts)
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>` containing an empty `logs/` subdirectory; no other agent process sharing `<scratch>`
- **estimate**: ≈ 20 minutes
- **motivation**: production defect 2026-08-24 — `_perform_refresh` claimed the process-lifetime single-flight slot before calling the bound `_build_launch_cmd()`; when the wrapper's configured-`venv_path` precheck raised, the slot stayed claimed and every corrected later refresh was silently skipped with `refresh_skipped(refresh_already_in_progress)` until the process was restarted by hand.

### Steps
1. From `<repo>`, run `python -m pytest tests/test_perform_refresh_handshake.py -q` and capture the outcome.
2. In `<scratch>`, construct a bare `BaseAgent` with an injected fake `RefreshWatcherPort` (record every `spawn_detached` call) and bind `agent._build_launch_cmd` to a callable that raises `RuntimeError` on its first call and returns `["python", "-c", "pass"]` afterwards. Call `agent._perform_refresh()` once and let the `RuntimeError` propagate.
3. Record, immediately after step 2: the number of `spawn_detached` calls; whether `<scratch>/.refresh` or `<scratch>/.refresh.taken` exists; `agent._shutdown.is_set()`; `agent._cancel_event.is_set()`; and `agent._refresh_started`.
4. Call `agent._perform_refresh()` a second time with the same agent and record the same observations plus every `refresh_skipped` / `refresh_deferred_relaunch` event the agent logged.
5. With a fresh agent in a fresh `<scratch>`, inject a fake `RefreshWatcherPort` whose `spawn_detached` records the call and then raises `OSError` on its first call only. Call `agent._perform_refresh()` once (let the `OSError` propagate) and record: `spawn_detached` call count, `agent._refresh_started`, `_shutdown.is_set()`, `_cancel_event.is_set()`, and whether `<scratch>/.refresh.taken` exists. Call `agent._perform_refresh()` a second time and record the call count, the `handshake` field of the `refresh_deferred_relaunch` event, and any `refresh_skipped` event.
6. With a fresh agent in a fresh `<scratch>`, bind `agent._log` so it raises `OSError` exactly when the event name is `refresh_deferred_relaunch`, call `agent._perform_refresh()` once (let the `OSError` propagate), then call it a second time; record `spawn_detached` call counts after each call and the second call's logged events.

### Expected evidence
- [ ] Step 1: the refresh handshake suite passes, including the single-flight coalescing and concurrent exact-one-watcher tests.
- [ ] Step 3 (failure before handshake normalization): zero `spawn_detached` calls; neither `.refresh` nor `.refresh.taken` exists; `_shutdown` and `_cancel_event` are both clear; `agent._refresh_started` is `False`.
- [ ] Step 4: the second call is not skipped — exactly one `spawn_detached` call in total, `.refresh.taken` exists, `_shutdown` and `_cancel_event` are set, one `refresh_deferred_relaunch` event, and no `refresh_skipped` event with reason `refresh_already_in_progress`.
- [ ] Step 5 (exception after ACK establishment): after the first call exactly one recorded `spawn_detached` call (the one that raised), `agent._refresh_started` is `False`, `_shutdown` and `_cancel_event` are both clear, and `.refresh.taken` is present (the established ACK is not rolled back — record its presence, do not require its absence). After the second call: two recorded calls, `refresh_deferred_relaunch` with `handshake=preexisting_taken`, and no `refresh_skipped` event with reason `refresh_already_in_progress`.
- [ ] Step 6: exactly one `spawn_detached` call after the first call and still exactly one after the second; the second call logs `refresh_skipped` with reason `refresh_already_in_progress`.

### Pass / Fail
Pass when every failure before `spawn_detached` returns leaves the slot released with no cancel/shutdown signal and the corrected retry completes exactly one handoff; a failure before handshake normalization additionally leaves no watcher call and no `.refresh`/`.refresh.taken` mutation, while an exception after the ACK was established may leave `.refresh.taken` in place; and a completed handoff (the Port's normal return) keeps the slot claimed. Fail if a retry after a raising launch-command build or a raising spawn is skipped as already-in-progress, if a pre-handshake failure spawns a watcher or mutates `.refresh`/`.refresh.taken`, if any pre-handoff failure sets `_shutdown`/`_cancel_event`, or if a post-handoff logging failure lets a later request spawn a second watcher; record the evidence trail in the task report.

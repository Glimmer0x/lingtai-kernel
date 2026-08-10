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

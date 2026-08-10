---
name: soul-behavior-tests
behavior_version: 1
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/soul/CONTRACT.md
  - src/lingtai/tools/soul/ANATOMY.md
  - src/lingtai/tools/soul/__init__.py
  - src/lingtai/tools/soul/flow.py
maintenance: |
  Created during the every-contract-needs-behaviors sweep. Keep this file
  reciprocal with CONTRACT.md and ANATOMY.md (tridirectional loop): when a soul
  tool behavior clause changes, update the guarding LABT here in the same
  change.
---
# Soul Capability Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/soul/CONTRACT.md` (flow opt-in gate, disabled/ongoing paths
return before spawning, manual no-op, envelope enforcement). Pinned pytest
commands must run from the repo root with the project's Python.

## Behavior SU001 — flow's disabled and ongoing paths return before any fire thread, and manual touches no soul state

- **id**: SU001
- **title**: flow's disabled and ongoing paths return before any fire thread, and manual touches no soul state
- **guards**: `soul-contract` § Tool surface
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; `LINGTAI_SOUL_FLOW_ENABLED` unset in the probe environment
- **estimate**: ≈ 15 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_soul.py tests/test_soul_consultation.py -q` and capture the outcome.
2. With `LINGTAI_SOUL_FLOW_ENABLED` unset, call `soul(action="flow", input={}, reasoning="probe")` and record the result; then set the variable and call `flow` twice in quick succession and record both results.
3. Call `soul(action="manual", input={}, reasoning="probe")` and confirm no timer, lock, consultation, config, voice, or notification state changed.

### Expected evidence
- [ ] Step 1: the soul suites pass, pinning inquiry/flow/config/voice/dismiss/manual behavior and consultation pair building.
- [ ] Step 2: with the env opt-out, `flow` returns `{status: "disabled", enabled: False, env_var, message}` and spawns no fire thread; a second `flow` while a fire is in flight returns `{error: "soul flow ongoing, request rejected"}` before spawning.
- [ ] Step 3: `manual` reads the installed manual and touches no soul state; a cross-action input key fails with `INVALID_ARGUMENT` before any handler I/O.

### Pass / Fail
Pass when the suites pass and the gate/no-op observations hold. Fail on a fire thread spawning when disabled or ongoing, on a `manual` that touches soul state, or on an accepted cross-action input; record the evidence trail in the task report.

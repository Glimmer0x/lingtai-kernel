---
name: system-behavior-tests
behavior_version: 1
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/system/karma.py
  - src/lingtai/tools/system/schema.py
  - src/lingtai/kernel/base_agent/CONTRACT.md
  - tests/test_karma.py
  - tests/_workdir_lease_helpers.py
  - tests/_snapshot_helpers.py
  - tests/_lifecycle_clock_helpers.py
  - tests/_notification_store_helpers.py
  - tests/_agent_presence_helpers.py
maintenance: |
  Written by the karma-lifecycle audit (2026-08). Keep in sync with
  CONTRACT.md clauses this file guards and ANATOMY.md entries for karma.py /
  name.py / preset.py; when CONTRACT.md or ANATOMY.md changes in a way that
  affects agent-observable lifecycle behavior, update the matching behavior
  here in the same change.
---
# System Behavior Tests — karma lifecycle control

These are agent-executable behavioral tests for the `system` tool's
karma-gated lifecycle verbs. They prove the *observable* promises of
`src/lingtai/tools/system/CONTRACT.md`: authorization gates, signal files,
state transitions, and self-action rejection. Low-level mechanics stay in
pytest; these scenarios run against a real agent pair.

## Behavior B001 — interrupt requires admin.karma

- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_interrupt_requires_karma_admin`
- **runner**: agent with `system` tool; a second agent dir exists
- **preconditions**: sender agent has `admin` block WITHOUT `karma` (e.g. `admin: {}`)

### Scenario
1. As the sender, call `system(action="interrupt", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Observe the result.

### Expected evidence
- [ ] The result contains an error (action refused) — `"error" in result`.
- [ ] No `.interrupt` signal file is written into the target agent's dir.

### Pass / fail
Pass when both evidence items hold. The receiver must never observe a
permission leak: an unprivileged caller cannot affect another agent.

## Behavior B002 — interrupt with admin.karma writes the signal file

- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_interrupt_with_karma_admin`
- **runner**: agent with `system` tool; a second agent dir exists with
  `.agent.json` and a fresh `.agent.heartbeat`
- **preconditions**: sender has `admin: {"karma": true}`; target dir is alive
  (heartbeat file present and recent)

### Scenario
1. As the sender, call `system(action="interrupt", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Observe the result and the target dir.

### Expected evidence
- [ ] The result status is `interrupted`.
- [ ] A `.interrupt` signal file exists in the target agent's working dir.

## Behavior B003 — lull writes the sleep signal and reports asleep

- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_lull_writes_signal_file`
- **runner**: agent with `system` tool; a second agent dir exists with
  `.agent.json` and a fresh `.agent.heartbeat`
- **preconditions**: sender has `admin: {"karma": true}`; target dir is alive

### Scenario
1. As the sender, call `system(action="lull", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Observe the result and the target dir.

### Expected evidence
- [ ] The result status is `asleep`.
- [ ] A `.sleep` signal file exists in the target agent's working dir.

## Behavior B004 — lull refuses an asleep target

- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_lull_rejects_asleep_target`
- **runner**: agent with `system` tool; a second agent dir with
  `.agent.json` carrying a non-null `admin` (so the not-running rejection path
  is exercised rather than the always-alive human shortcut)
- **preconditions**: sender has `admin: {"karma": true}`; target has no
  heartbeat or is not alive

### Scenario
1. As the sender, call `system(action="lull", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Observe the result.

### Expected evidence
- [ ] The result contains an error (action refused because the target is not
      alive/asleep already).

## Behavior B005 — self-action is rejected

- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_interrupt_self_rejected`
- **runner**: agent with `system` tool
- **preconditions**: sender has `admin: {"karma": true}`; the address passed
  is the sender's own working dir

### Scenario
1. As the sender, call `system(action="interrupt", input={"address": "<own-working-dir>", "reason": "test"})`.
2. Observe the result.

### Expected evidence
- [ ] The result contains an error (an agent cannot karma-act on itself).
- [ ] No `.interrupt` signal file is created in the sender's own dir.

## Behavior B006 — nirvana requires nirvana privilege

- **guards**: `system-contract` § Nirvana
  ([CONTRACT.md](CONTRACT.md#nirvana))
- **supersedes**: `tests/test_karma.py::test_nirvana_requires_nirvana_admin`
- **runner**: agent with `system` tool; a second agent dir exists
- **preconditions**: sender has `admin: {"karma": true}` but NOT
  `admin.nirvana`; target dir is alive

### Scenario
1. As the sender, call `system(action="nirvana", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Observe the result.

### Expected evidence
- [ ] The result contains an error (nirvana is refused without
      `admin.karma AND admin.nirvana`).
- [ ] The target agent dir is NOT destroyed.

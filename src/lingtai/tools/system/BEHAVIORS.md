---
name: system-behavior-tests
behavior_version: 3
labt_version: 2
contract: CONTRACT.md
anatomy: ANATOMY.md
related_files:
  - src/lingtai/tools/system/karma.py
  - src/lingtai/tools/system/schema.py
  - src/lingtai/tools/system/settings.py
  - src/lingtai/agent.py
  - src/lingtai/kernel/meta_block.py
  - src/lingtai/intrinsic_skills/system-manual/SKILL.md
  - src/lingtai/tools/context/manual/SKILL.md
  - src/lingtai/kernel/base_agent/CONTRACT.md
  - tests/test_karma.py
  - tests/test_system_declared_plugin.py
  - tests/test_meta_block.py
  - tests/test_init_reader.py
  - tests/_workdir_lease_helpers.py
  - tests/_snapshot_helpers.py
  - tests/_lifecycle_clock_helpers.py
  - tests/_notification_store_helpers.py
  - tests/_agent_presence_helpers.py
maintenance: |
  Written by the karma-lifecycle audit (2026-08). Keep in sync with
  CONTRACT.md clauses this file guards and ANATOMY.md entries for karma.py /
  name.py / preset.py / the System-owned cache-miss budget resolver; when CONTRACT.md or
  ANATOMY.md changes in a way that affects agent-observable lifecycle behavior,
  update the matching LABT here
  in the same change.
---
# System Behavior Tests — karma lifecycle control

LABT v1. These are self-contained agent-executable behavioral tests for the
`system` tool's karma-gated lifecycle verbs. They prove the *observable*
promises of `src/lingtai/tools/system/CONTRACT.md`: authorization gates, signal
files, state transitions, and self-action rejection. Low-level mechanics stay
in pytest; each LABT below is self-contained and executable verbatim by an
agent with a `system` tool.

## Behavior B001 — interrupt requires admin.karma

- **id**: B001
- **title**: interrupt is refused without admin.karma
- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_interrupt_requires_karma_admin`
- **runner**: an agent whose `admin` block does NOT include `karma` (e.g. `admin: {}`)
- **prerequisites**: a second agent working dir exists (a dir containing
  `.agent.json` and a fresh `.agent.heartbeat`)
- **estimate**: 1 min

### Steps
1. From your working dir, call `system(action="interrupt", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Read the result returned by the tool.
3. List the files in `<target-agent-dir>` and look for `.interrupt`.

### Expected evidence
- [ ] The result contains an error (action refused).
- [ ] No `.interrupt` file exists in `<target-agent-dir>`.

### Pass / Fail
Pass when both evidence items hold. Fail if the action succeeds or any
signal file was written. An unprivileged caller must never affect another
agent.

## Behavior B002 — interrupt with admin.karma writes the signal file

- **id**: B002
- **title**: interrupt with admin.karma writes `.interrupt` into the target
- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_interrupt_with_karma_admin`
- **runner**: an agent with `admin: {"karma": true}`
- **prerequisites**: a second agent working dir exists with `.agent.json` and
  a fresh `.agent.heartbeat` (so the target is considered alive)
- **estimate**: 1 min

### Steps
1. From your working dir, call `system(action="interrupt", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Read the result.
3. List the files in `<target-agent-dir>`.

### Expected evidence
- [ ] The result status is `interrupted`.
- [ ] A `.interrupt` file exists in `<target-agent-dir>`.

### Pass / Fail
Pass when the receipt says `interrupted` AND the signal file exists. Fail if
the signal file is missing or the receipt is an error.

## Behavior B003 — lull writes the sleep signal and reports asleep

- **id**: B003
- **title**: lull with admin.karma puts the target to sleep
- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_lull_writes_signal_file`
- **runner**: an agent with `admin: {"karma": true}`
- **prerequisites**: a second agent working dir exists with `.agent.json` and
  a fresh `.agent.heartbeat` (target alive)
- **estimate**: 1 min

### Steps
1. From your working dir, call `system(action="lull", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Read the result.
3. List the files in `<target-agent-dir>`.

### Expected evidence
- [ ] The result status is `asleep`.
- [ ] A `.sleep` file exists in `<target-agent-dir>`.

### Pass / Fail
Pass when the receipt says `asleep` AND the `.sleep` signal file exists.

## Behavior B004 — lull refuses a target that is not alive

- **id**: B004
- **title**: lull refuses an asleep/non-alive target
- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_lull_rejects_asleep_target`
- **runner**: an agent with `admin: {"karma": true}`
- **prerequisites**: a second agent working dir exists whose `.agent.json`
  carries a non-null `admin` (so the not-running rejection path is exercised
  rather than the always-alive human shortcut); the target has no fresh
  heartbeat
- **estimate**: 1 min

### Steps
1. From your working dir, call `system(action="lull", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Read the result.

### Expected evidence
- [ ] The result contains an error (refused because the target is not alive).

### Pass / Fail
Pass when the action is refused with an error. Fail if lull reports success
against a dead target.

## Behavior B005 — self-action is rejected

- **id**: B005
- **title**: an agent cannot karma-act on itself
- **guards**: `system-contract` § Karma-gated control of other agents
  ([CONTRACT.md](CONTRACT.md#karma-gated-control-of-other-agents))
- **supersedes**: `tests/test_karma.py::test_interrupt_self_rejected`
- **runner**: an agent with `admin: {"karma": true}`
- **prerequisites**: none beyond your own working dir
- **estimate**: 1 min

### Steps
1. From your working dir, call `system(action="interrupt", input={"address": "<your-own-working-dir>", "reason": "test"})`.
2. Read the result.
3. List your own working dir.

### Expected evidence
- [ ] The result contains an error (self-action refused).
- [ ] No `.interrupt` file exists in your own working dir.

### Pass / Fail
Pass when self-interrupt is refused and no signal file is created. Fail if
an agent can interrupt itself.

## Behavior B006 — nirvana requires nirvana privilege

- **id**: B006
- **title**: nirvana needs admin.karma AND admin.nirvana
- **guards**: `system-contract` § Nirvana
  ([CONTRACT.md](CONTRACT.md#nirvana))
- **supersedes**: `tests/test_karma.py::test_nirvana_requires_nirvana_admin`
- **runner**: an agent with `admin: {"karma": true}` but NOT `admin.nirvana`
- **prerequisites**: a second agent working dir exists and is alive
- **estimate**: 1 min

### Steps
1. From your working dir, call `system(action="nirvana", input={"address": "<target-agent-dir>", "reason": "test"})`.
2. Read the result.
3. Check whether `<target-agent-dir>` still exists.

### Expected evidence
- [ ] The result contains an error (nirvana refused without nirvana admin).
- [ ] The target agent dir still exists (not destroyed).

### Pass / Fail
Pass when nirvana is refused AND the target is untouched. Fail if nirvana
succeeds with only karma privilege.

## Behavior B007 — CPR distinguishes an observed exit from an unconfirmed live launch

- **id**: B007
- **title**: CPR does not report a still-running child failed solely for a delayed heartbeat
- **guards**: `system-contract` § [CPR launch confirmation](CONTRACT.md#cpr-launch-confirmation)
- **supersedes**: `tests/test_karma.py::TestCPRLingtai::test_cpr_agent_returns_unconfirmed_running_child`,
  `tests/test_karma.py::TestCPRLingtai::test_cpr_agent_reports_early_exit_before_heartbeat`,
  `tests/test_karma.py::TestCPRLingtai::test_cpr_agent_reports_exit_observed_at_confirmation_deadline`
- **runner**: an agent with `admin: {"karma": true}` and the hermetic CPR-launch harness
- **prerequisites**: a disposable non-human target agent directory with `init.json`; the
  harness can hold its heartbeat observation false, advance the runtime-policy
  confirmation interval (`max(10 seconds, 2 * HEARTBEAT_LIVENESS_SECONDS)`;
  20 seconds by default and scaled by valid `LINGTAI_AGENT_ALIVE_THRESHOLD_SEC` overrides)
  without wall-clock waiting, and control the detached child's `poll()` result
- **estimate**: 1 min

### Steps
1. Launch CPR against the disposable target with its fresh-heartbeat observation held
   false while the fake detached child remains running (`poll()` returns `None`), then
   advance the confirmation interval to its boundary.
2. Inspect the CPR result and the reviver's lifecycle events.
3. Repeat with no fresh heartbeat and a child exit observed by `poll()` (including exit
   code zero); inspect the result and relaunch-log diagnostic.

### Expected evidence
- [ ] The still-running case returns the established `resuscitated` receipt and records
  `cpr_launch_unconfirmed`; it does not record `cpr_timeout` or return a launch error.
- [ ] The observed-exit case returns an error with the exact `exit_code`, relaunch-log
  path, and bounded log-tail diagnostic; it does not report `resuscitated`.
- [ ] Both cases retain the bounded confirmation interval derived from
  `max(10 seconds, 2 * HEARTBEAT_LIVENESS_SECONDS)` (20 seconds by default and scaled by
  valid `LINGTAI_AGENT_ALIVE_THRESHOLD_SEC` overrides); the live-child receipt is not
  evidence of continuing health after CPR returns.

### Pass / Fail
Pass when absence of heartbeat evidence is distinguished from an observed child exit as
above. Fail if CPR calls a still-running child failed solely for missing confirmation, or
if any observed exit is reported as `resuscitated`.


## Behavior B008 — mounted and direct sleep preserve refusal/force parity

- **id**: B008
- **title**: pending attention refuses ordinary sleep but explicit force may sleep
- **guards**: `system-contract` § [Single sleep use case](CONTRACT.md#single-sleep-use-case)
- **supersedes**: `tests/test_karma.py::TestSelfSleepPendingNotificationsGuard::test_sleep_refused_when_notification_pending`, `tests/test_karma.py::TestSelfSleepPendingNotificationsGuard::test_sleep_force_true_overrides_pending_guard`
- **runner**: an agent with a disposable working directory, exercised once through the registrar-mounted `system` handler and once through the compatibility `handle(agent, args)` entry point
- **prerequisites**: write one disposable `.notification/email.json` payload after seeding an empty committed attention fingerprint; no real peer or operator directory
- **estimate**: 1 min

### Steps
1. Call `system(action="sleep", input={"reason": "test", "force": false})` through each entry point and inspect the receipt/state.
2. Repeat with `force: true`.
3. Confirm only the forced cases transition to ASLEEP; clean the disposable directory.

### Expected evidence
- [ ] Both ordinary calls return the established `ok` refusal receipt and remain awake.
- [ ] Both forced calls return the established sleep receipt and transition to ASLEEP.
- [ ] No non-disposable path is read, written, or removed.

### Pass / Fail
Pass only when mounted and direct routes agree on refusal, force escape, receipt, and state transition. A route that reimplements or weakens the pending-attention guard fails.

## Behavior B009 — System cache-miss budget live settings preserve the counter

- **id**: B009
- **title**: System's live budget setting changes the soft threshold without resetting since-last-molt usage
- **guards**: `system-contract` § [Cache-miss budget family settings](CONTRACT.md#cache-miss-budget-family-settings)
- **supersedes**: `tests/test_system_declared_plugin.py` System settings tests; `tests/test_meta_block.py` hook/fallback/telemetry tests; `tests/test_init_reader.py::test_real_reader_reports_ignored_legacy_paths_without_mutating_input`
- **runner**: a disposable real LingTai agent with `file`, `shell`, and `system`, whose launch environment does not set `LINGTAI_CACHE_MISS_BUDGET`
- **prerequisites**: the executor owns the disposable `<WD>` and may write `<WD>/settings/system.json`; do not use a real agent runtime/config directory
- **estimate**: 2 min

### Steps
1. Before creating the settings file, call `system(action="manual", input={}, reasoning="Read System's installed manual as a read-only carrier for B009 metadata.", summarize=false)`. Record the newest `_meta.agent_meta.agent_state.token_usage.session` values for `cache_miss_tokens`, `cache_miss_budget`, and `cache_miss_remaining_tokens`; the budget must be `2000000`.
2. Write `<WD>/settings/system.json` as exactly `{"schema_version": 1, "cache_miss_budget": 1}`. Without refresh/restart, call `system(action="manual", input={}, reasoning="Read System's installed manual as a read-only carrier for B009 metadata.", summarize=false)` and inspect the newest metadata snapshot.
3. Replace the file with exactly `{"schema_version": 1, "cache_miss_budget": 3000000}`. Without refresh/restart, call `system(action="manual", input={}, reasoning="Read System's installed manual as a read-only carrier for B009 metadata.", summarize=false)` and inspect the newest snapshot.
4. Replace the file with the malformed text `{`. Call `system(action="manual", input={}, reasoning="Read System's installed manual as a read-only carrier for B009 metadata.", summarize=false)` twice and inspect both newest snapshots. Then run this exact bounded read-only query:

   ```text
   shell(action="run", input={"command": "tail -n 200 -- logs/events.jsonl | python -c 'import json,sys; rows=(json.loads(line) for line in sys.stdin if line.strip()); matches=[{key: row.get(key) for key in (\"event\",\"settings_path\",\"reason\",\"fallback_budget\")} for row in rows if row.get(\"event\")==\"cache_miss_budget_settings_invalid\"]; print(json.dumps(matches, sort_keys=True))'", "timeout": 30, "working_dir": "<WD>", "async": false, "reminder": null}, reasoning="Inspect a bounded event tail for the cache-miss settings diagnostic.", summarize=false)
   ```

5. Confirm no step created, rewrote, or consumed `<WD>/.notification/system.json` and no request was blocked.

### Expected evidence
- [ ] Step 1 reports default `cache_miss_budget == 2000000`.
- [ ] Step 2 live-applies budget `1`; `cache_miss_tokens` does not reset or decrease, and the at-budget soft `context.molt` line is present.
- [ ] Step 3 live-applies budget `3000000`; `cache_miss_tokens` still does not reset or decrease and remaining tokens are recomputed from that same cumulative total.
- [ ] Both Step 4 snapshots fall back to `cache_miss_budget == 2000000`. The bounded query prints exactly `[{"event": "cache_miss_budget_settings_invalid", "fallback_budget": 2000000, "reason": "malformed_json", "settings_path": "settings/system.json"}]`: exactly one event, containing only the expected event name, static relative path, reason code, and fallback scalar across both calls.
- [ ] `.notification/system.json` is untouched and every tool call completes normally.

### Pass / Fail
Pass when every checklist item holds, the Step 4 query returns exactly the one
four-field object shown, and no forbidden side effect occurs. Fail if a refresh
is required for the file, a threshold change resets usage, malformed JSON becomes
effective, the diagnostic repeats for unchanged bytes, the bounded query omits or
adds a field/event, or the soft guard blocks a request.

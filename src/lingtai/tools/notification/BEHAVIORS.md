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
  the same change. N001-N003 guard the notification hook-registry clauses
  added by PR #1337 (unregistered channel blocked, registered channel
  passes through, lifecycle validation).
---
# Notification Tool Behavior Tests

Self-contained agent behavior tasks guarding the observable behavior clauses of
`src/lingtai/tools/notification/CONTRACT.md` (manual read-only, check/current
state, narrow dismiss actions, hook-registry allowlist, Store semantics
preserved). Pinned pytest commands must run from the repo root with the
project's Python.

## Behavior N001 — unregistered channels are blocked; manual stays read-only

- **id**: N001
- **title**: notification check reports current state without mutating producer state, and an unregistered hook channel is blocked with a `blocked_channel:<channel>` system event
- **guards**: `notification-tool` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a clean checkout of `<repo>`; a scratch agent working directory `<scratch>` with a populated `.notification/`
- **estimate**: ≈ 15 minutes

### Steps
1. From `<repo>`, run `python -m pytest tests/test_notification_tool.py -q` and capture the outcome.
2. Call `notification(action="manual", input={}, reasoning="probe")` and record the result; hash `.notification/` before and after.
3. Call `notification(action="check", input={}, reasoning="probe")` and confirm it reports current channel state without mutating it.
4. Publish an event to an unregistered channel (e.g. write `.notification/unregistered.json`) and confirm a `blocked_channel:<channel>` system event is emitted.

### Expected evidence
- [ ] Step 1: the notification-tool suite passes.
- [ ] Step 2: `manual` returns installed per-agent guidance; `.notification/` is byte-identical.
- [ ] Step 3: `check` reports current state without mutating it.
- [ ] Step 4: the unregistered channel is blocked and the system event names it.

### Pass / Fail
Pass when the suite passes, read-only manual/check observations hold, and the unregistered channel is blocked with the named system event. Fail on a mutating `manual`, on `check` changing state, or on an unregistered channel passing through; record the evidence trail in the task report.

## Behavior N002 — registered hook channels pass through

- **id**: N002
- **title**: an event published to a registered hook channel passes through to notifications
- **guards**: `notification-tool` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a scratch agent working directory `<scratch>` with a registered hook channel (see `notification(action="add", ...)`)
- **estimate**: ≈ 10 minutes

### Steps
1. Register a hook channel (e.g. `notification(action="add", input={"name": "probe", "channel": "mcp.probe", ...})`).
2. Publish an event to `.notification/mcp.probe.json`.
3. Call `notification(action="check", input={}, reasoning="probe")` and confirm the event is reported.

### Expected evidence
- [ ] The hook manifest is written to `.notification/hooks.json` and the channel is allowlisted.
- [ ] The published event appears in `notification(action="check")` output.

### Pass / Fail
Pass when the registered channel's event is reported. Fail if it is blocked or dropped; record the evidence trail in the task report.

## Behavior N003 — hook-registry lifecycle validation

- **id**: N003
- **title**: notification hook add/drop/edit/list validate inputs and keep the manifest consistent
- **guards**: `notification-tool` § Behavior
- **runner**: any LingTai agent with `shell` and `file` access to this repository
- **prerequisites**: a scratch agent working directory `<scratch>` with `.notification/` writable
- **estimate**: ≈ 10 minutes

### Steps
1. Call `notification(action="add", input={"name": "dup", "channel": "mcp.dup", ...})` twice and confirm the second add is refused as a duplicate.
2. Call `notification(action="edit", input={"name": "dup", ...})` to change its description, then `list` to confirm the edit landed.
3. Call `notification(action="drop", input={"name": "dup"})` and confirm `list` no longer shows it and the channel is revoked from the effective allowlist.

### Expected evidence
- [ ] Duplicate add refused; edit reflected in list; drop removes manifest and revokes the channel.
- [ ] `.notification/hooks.json` stays valid JSON throughout.

### Pass / Fail
Pass when add/edit/drop behave as above and the manifest stays valid. Fail on silent acceptance of duplicates or a manifest left inconsistent; record the evidence trail in the task report.

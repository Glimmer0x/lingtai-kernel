---
name: daemon-dispatch-ledger
version: 0.1.0
last_changed_at: 2026-08-25T06:09:40Z
related_files:
- src/lingtai/tools/daemon/manual/SKILL.md
- src/lingtai/tools/daemon/CONTRACT.md
- src/lingtai/tools/daemon/ANATOMY.md
- src/lingtai/tools/daemon/dispatch_ledger.py
- src/lingtai/kernel/daemon_dispatch.py
maintenance: |
  Update this operational reference with the dispatch ledger contract and keep
  it discoverable from the daemon manual router.
---
# Dispatch Ledger Diagnostics

The agent-local `daemons/.dispatch-ledger.jsonl` is append-only membership and
acceptance order for new daemon runs. It records only `schema`, monotonic
`sequence`, `run_id`, and informational `created_at`. It is not daemon status:
read the ledger-selected run's `daemon.json` for lifecycle, result, and usage.
Small `.dispatch-recovery/` markers contain only unresolved running and pending
terminal-notification work for startup recovery.

## Normal operation

- A new agent or a cutover agent may have no ledger. This is normal; legacy run
  directories are not automatically backfilled.
- Default `daemon(action="list", input={})` tails the newest 1000 records in
  append order. It does not sort timestamps, enumerate historical folders, or
  make a materialized index.
- Exact `daemon(check)` and explicit/manual filesystem inspection remain the
  way to inspect a known legacy run id. Do not infer an omitted list item means
  it was deleted or failed.
- The owning Agent Record refreshes a recent ledger-selected daemon summary in
  one coalescing background snapshot. It is intentionally eventual so heartbeat
  liveness is independent of storage latency.

## Warnings

`daemon(list)` warnings are advisory and include a checked range/scope, count,
bounded examples where relevant, and this manual path. They never repair files.

| Code | What the observation means |
|---|---|
| `dispatch_ledger_empty` | No records exist in the checked tail. This is expected for a new/cutover agent, but it can also mean that the ledger is absent. |
| `dispatch_ledger_invalid_record` | JSON or the four-field ledger schema is invalid in the checked range. |
| `dispatch_ledger_sequence_non_monotonic` | File order in the checked range contains a sequence gap, reversal, or non-contiguous value. Timestamps are informational and do not define order. |
| `dispatch_ledger_duplicate_run_id` | One accepted run id appears more than once in the checked range. |
| `dispatch_ledger_daemon_state_unreadable` | A ledger-selected run's authoritative `daemon.json` is missing, corrupt, or unreadable. |

A malformed final ledger record is stricter than a read warning: future
acceptance refuses before launch because the next sequence cannot be proven. No
runtime path truncates, repairs, sorts, migrates, or rebuilds the ledger. The
manual describes these mechanics and observations only; the agent/human reasons
separately about whether any intervention is appropriate.

---
name: daemon-dispatch-ledger
version: 0.1.0
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

| Code | Meaning | Next safe step |
|---|---|---|
| `dispatch_ledger_empty` | No records in the checked tail (new/cutover agent or absent ledger). | Check a known run id explicitly if needed; do not backfill automatically. |
| `dispatch_ledger_invalid_record` | JSON/schema was invalid in this checked range. | Preserve evidence and ask the owner how to diagnose it. |
| `dispatch_ledger_sequence_non_monotonic` | The checked records have a gap, reversal, or non-contiguous sequence. | Do not reorder or rewrite; inspect the exact ledger/run ids deliberately. |
| `dispatch_ledger_duplicate_run_id` | A run id repeats in the checked range. | Treat `daemon.json` as status truth; escalate rather than deduplicating history. |
| `dispatch_ledger_daemon_state_unreadable` | A selected run's `daemon.json` was missing/corrupt/unreadable. | Use exact `check`/forensics and let the owner decide recovery. |

A malformed final ledger record is stricter than a read warning: future
acceptance refuses before launch because the next sequence cannot be proven. No
runtime path truncates, repairs, sorts, migrates, or rebuilds the ledger. The
agent/human decides whether and how to repair evidence outside this automatic
path.

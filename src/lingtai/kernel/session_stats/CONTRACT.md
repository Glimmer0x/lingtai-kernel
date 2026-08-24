---
name: session-stats
contract_version: 2
root_contract: CONTRACT.md
related_files:
  - src/lingtai/kernel/session_stats/ANATOMY.md
  - src/lingtai/kernel/session_stats/__init__.py
  - src/lingtai/kernel/daemon_dispatch.py
  - src/lingtai/kernel/base_agent/CONTRACT.md
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - src/lingtai/tools/daemon/CONTRACT.md
  - src/lingtai/tools/daemon/run_dir.py
  - src/lingtai/mcp_servers/telegram/manager.py
  - tests/test_session_stats.py
  - tests/test_daemon_dispatch_ledger.py
  - ENVIRONMENT_VARIABLES.md
maintenance: |
  <!-- CANONICAL-MAINTENANCE v2 BEGIN -->
  This component contract is governed by the root CONTRACT.md. Keep
  related_files complete and repo-relative: the paired ANATOMY.md, Port, every
  production Adapter, contract tests, and directly relevant component contracts
  belong here. Re-read this contract whenever a linked boundary changes. Update
  the Port, affected Adapters, contract tests, and this contract in the same
  change; update the paired Anatomy when structure or composition also changes;
  bump contract_version for a breaking Port-contract change. If code and contract
  disagree, treat the disagreement as a defect—do not silently rewrite the
  normative contract to match the implementation.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
  <!-- CANONICAL-MAINTENANCE END -->
---
# Agent Record / Session Stats

## Purpose

Each Agent publishes one atomic, versioned, redacted Agent Record. Presentation
consumers read that record rather than reconstructing normal live status. The
record's daemon block is a bounded recent dispatch view: append-order membership
comes only from the dispatch ledger and each selected `daemon.json` is status
and usage truth.

## Behavior

`build_agent_record`/`write_agent_record` are the only normal Agent Record
writer. They never serialize secrets, environment/config values, prompt/message
or tool payloads, paths, PIDs, shell commands, or unbounded task text. The
record writer is best-effort and its throttle remains live-configured by
`LINGTAI_SESSION_STATS_REFRESH_SECONDS`.

`aggregate_daemon_records` MUST read at most
`LINGTAI_SESSION_STATS_DAEMON_LIMIT` (default 1000) records from the dispatch
ledger EOF tail and only the `daemon.json` files those records name. It MUST NOT
enumerate, stat, sort, backfill, or repair run directories. `created_at` MUST
NOT determine order. `present` is the number of ledger records in the checked
range; `scanned` is the subset with readable state. Missing/corrupt state is a
bounded diagnostic, not fabricated usage.

The heartbeat MUST NOT await aggregation. `RecentDaemonSnapshot` is the named
single-flight boundary: heartbeat code schedules/coalesces a refresh and
publishes the latest completed snapshot. A blocked read must not prevent
liveness publication. No per-run `session_stats.json` duplicate is written.

## Shapes

Agent Record fields remain `schema`, `schema_version`, `generated_at`,
`sequence`, `identity`, `model`, `handles`, `integrations`, `session`, `health`,
`usage`, and `daemons`. The daemon summary contains `source` (`dispatch_ledger`),
`present`, `scanned`, `limit`, `counts_by_state`, `usage`, checked-range metadata,
bounded warnings, and `refreshing`. Warning facts are advisory only and are
never an authorization to repair or clean artifacts.

## Contract rules

1. Agent Record writes are atomic through `kernel._fsutil.atomic_write_json`.
2. `BaseAgent._write_session_stats_record` is best-effort and schedules, rather
   than waits for, daemon aggregation.
3. The aggregation source is the append-only dispatch ledger; legacy directories
   without a ledger record remain invisible until exact/manual inspection.
4. An empty/malformed/unreadable checked source never triggers automatic repair,
   reorder, truncation, or fallback scan.
5. `DaemonRunDir._persist_daemon_state` writes authoritative `daemon.json` and
   recovery markers only; it does not write duplicate session statistics.

## Contract tests

`tests/test_session_stats.py` protects Agent Record publication/redaction,
ledger-selected bounded aggregation, checked warnings, and snapshot
single-flight behavior. `tests/test_daemon_dispatch_ledger.py` protects append
sequence, malformed-tail refusal, bounded tail diagnostics, and markers.

## Maintenance

Read the paired Anatomy for composition. Update the projector, BaseAgent hook,
ledger boundary, daemon owner docs, and tests together.

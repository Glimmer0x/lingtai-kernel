---
related_files:
  - src/lingtai/kernel/session_stats/CONTRACT.md
  - src/lingtai/kernel/session_stats/__init__.py
  - src/lingtai/cli.py
  - tests/test_session_stats.py
  - tests/test_cli_liveness.py
  - src/lingtai/kernel/ANATOMY.md
  - src/lingtai/kernel/base_agent/ANATOMY.md
  - src/lingtai/kernel/base_agent/CONTRACT.md
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - src/lingtai/kernel/base_agent/identity.py
  - src/lingtai/kernel/config.py
  - src/lingtai/kernel/lifecycle_clock/CONTRACT.md
  - src/lingtai/agent.py
  - src/lingtai/services/mcp_registry.py
  - src/lingtai/tools/daemon/ANATOMY.md
  - src/lingtai/tools/daemon/run_dir.py
  - src/lingtai/mcp_servers/telegram/manager.py
  - src/lingtai/mcp_servers/local_commands/core.py
  - ENVIRONMENT_VARIABLES.md
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  Keep this component's ANATOMY.md and CONTRACT.md reciprocal and keep
  parent/child anatomy links bidirectional. Code is the structural source of
  truth: update this anatomy in the same change that moves files, symbols,
  connections, composition, or state. Verify every changed citation and run the
  architecture-document validation before merge.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# Agent Record / Session Stats

This folder owns the kernel's one live, redacted, versioned personal record for
each Agent, plus the compact per-turn self-record each daemon publishes and the
bounded aggregation that folds present daemon self-records into the owning
agent's record. It is the sole normal-live-status source: presentation
consumers (TUI, `/kanban`, `/details`, Telegram, Portal) read and curate this
record instead of independently re-collecting `.status.json`/heartbeat/daemon
state (confirmed alignment: Telegram 14238/14242/14248).

## Components

- `build_agent_record` / `write_agent_record` / `read_agent_record` /
  `classify_published_agent_record` / `query_published_agent_liveness`
  (`__init__.py`) — the Agent record projector, atomic writer, best-effort
  reader, pure classifier, and one-key consumer dict projection. The projection
  receives the reader's current wall time, ignores persisted `health.liveness`,
  maps a stale active/idle/asleep record to `offline`, and makes malformed or
  absent records `unavailable`. `lingtai-agent liveness --agent-dir <dir>`
  (`cli.py`) is the read-only cross-process JSON wrapper around that projection;
  neither Python nor cross-process consumers reconstruct heartbeat semantics.
  Publishes to `system/agent_record.json`.
- `build_daemon_record` / `write_daemon_record` (`__init__.py`) — the compact
  daemon self-record projector and atomic writer. Publishes to
  `<run_dir>/session_stats.json`, a sibling of `daemon.json`.
- `aggregate_daemon_records` (`__init__.py`) — bounded newest-N-present scan
  over `<working_dir>/daemons/*/session_stats.json`.
- `session_stats_refresh_seconds` / `session_stats_daemon_limit` /
  `should_refresh_agent_record` (`__init__.py`) — validated environment
  configuration (`LINGTAI_SESSION_STATS_REFRESH_SECONDS`,
  `LINGTAI_SESSION_STATS_DAEMON_LIMIT`) and the main-record refresh throttle.

## Connections

- `BaseAgent._write_session_stats_record` (`kernel/base_agent/__init__.py`)
  calls `build_agent_record`/`write_agent_record` from the same three hooks
  that already call `_write_status_snapshot`
  (`base_agent/__init__.py::_save_chat_history`,
  `base_agent/lifecycle.py`'s ACTIVE-without-progress watchdog and
  `_write_heartbeat_tick`), throttled by `session_stats_refresh_seconds()`.
  `BaseAgent._build_agent_record_extra` is the Core-side extension point
  (returns `{}`); `lingtai.Agent` overrides it
  (`agent.py::_build_agent_record_extra`) to add `handles`/`integrations` from
  `services.mcp_registry.read_registry`/`read_identities` — Core itself never
  imports MCP/Telegram modules.
- `build_agent_record` reads `agent._lifecycle_clock`, `agent.get_token_usage()`,
  `agent._state`, `agent._heartbeat`, `agent._molt_count`, and
  `base_agent.identity._safe_llm_from_service` — all data Core already owns —
  plus `HEARTBEAT_LIVENESS_SECONDS` from `kernel/config.py` for the shared
  fresh/stale liveness threshold (the same constant the agent-presence store
  uses, so no second liveness window exists).
- `DaemonRunDir._persist_daemon_state` (`tools/daemon/run_dir.py`) is the one
  chokepoint every `daemon.json` write already funnels through (turn bump,
  tool dispatch, CLI output/usage, terminal markers, …); it now also calls
  `write_daemon_record`, so the daemon self-record refreshes on every daemon
  turn without a second scattered set of call sites.
- `TelegramManager._task_card_agent_lifecycle_status` delegates the automatic
  Task Card lifecycle to `classify_published_agent_record` after
  `read_agent_record`; `_task_card_active_seconds`
  (`mcp_servers/telegram/manager.py`) and
  `LocalCommandCore.collect_kanban_data` (`mcp_servers/local_commands/core.py`)
  read the record instead of `.status.json`/token-ledger scans.

## Composition

- **Parent:** `src/lingtai/kernel/` (see [`ANATOMY.md`](../ANATOMY.md)).
- **Paired contract:** [`CONTRACT.md`](CONTRACT.md) owns the record shapes,
  redaction rules, throttling/bounding behavior, and the extension-point
  contract with `lingtai.Agent`.
- **Sibling relationship:** shares the atomic-write primitive
  (`kernel/_fsutil.atomic_write_json`) with `.status.json`/`.agent.json`/
  `system/manifest.resolved.json`, and the liveness threshold with
  `kernel/agent_presence` — it does not duplicate either mechanism.

## State

The module itself is stateless — every read/write is a pure function of its
argument plus the filesystem at call time. The two pieces of persisted process
state live on the calling `BaseAgent`: `_session_stats_last_written_at` (wall
seconds, throttle anchor) and `_session_stats_sequence` (process-local
monotonic counter, resets on restart — atomic replace already makes torn reads
impossible; the sequence is a bonus ordering signal, not a durability
guarantee).

## Notes

Avatars need no special case: an avatar is an ordinary `Agent` bound to its own
working directory, so it gets its own Agent record through the same hooks.
Daemon self-records are written unconditionally on every turn (no throttle);
only the owning agent's own record write is throttled, since it is the one
that re-scans `daemons/*/session_stats.json`. A daemon without a self-record is
never backfilled from `daemon.json` or inferred — it is simply absent from
`aggregate_daemon_records`'s `present`/`scanned` counts.

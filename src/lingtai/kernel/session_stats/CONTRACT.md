---
name: session-stats
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/kernel/session_stats/ANATOMY.md
  - src/lingtai/kernel/session_stats/__init__.py
  - src/lingtai/kernel/base_agent/CONTRACT.md
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - src/lingtai/kernel/base_agent/identity.py
  - src/lingtai/kernel/config.py
  - src/lingtai/kernel/agent_presence/CONTRACT.md
  - src/lingtai/agent.py
  - src/lingtai/services/mcp_registry.py
  - src/lingtai/tools/daemon/run_dir.py
  - src/lingtai/mcp_servers/telegram/manager.py
  - src/lingtai/mcp_servers/local_commands/core.py
  - ENVIRONMENT_VARIABLES.md
  - tests/test_session_stats.py
  - tests/test_daemon_run_dir.py
  - tests/test_status_snapshot.py
  - tests/test_architecture_documents.py
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

Every LingTai Agent — including avatars — owns and publishes exactly one live,
atomic, versioned, redacted personal record: identity, model/provider,
verified consumer-facing handles, visible MCP integration labels, session and
liveness, usage/context, and a bounded aggregate of its own daemons. This is
the sole source presentation surfaces (TUI normal live status, `/kanban`,
`/details` stats, Telegram status retrieval, Portal live display) may use for
normal live status; they curate and render it, they do not independently
re-collect it. Each daemon separately publishes its own compact self-record on
every daemon turn; the owning agent aggregates ONLY present, bounded,
newest-first daemon self-records. This is a direct migration: there is no
old-consumer fallback that reconstructs duplicate truth from `.status.json`,
heartbeat files, or raw daemon-directory scans.

## Behavior

Runtime and coding agents MUST publish the Agent record only through
`build_agent_record`/`write_agent_record` and the daemon self-record only
through `build_daemon_record`/`write_daemon_record`; no other writer may
create `system/agent_record.json` or `<run_dir>/session_stats.json`. Both
writes MUST be atomic (temp file + `os.replace`, via the shared
`kernel._fsutil.atomic_write_json`) so a reader never observes a partial
document. Every record MUST carry `schema`, `schema_version`, and
`generated_at`; a reader MUST treat an unrecognized `schema` value as absent
rather than parsing it. Missing or corrupt records MUST be surfaced by callers
as explicitly stale/unavailable — never silently recomputed from a legacy
source, never faked as zero, never partially backward-compatible.

The Agent record MUST NOT contain: API keys/tokens/passwords, environment or
config values, raw prompts/system-prompt sections/model messages/tool
arguments or results, mail/inbox/notification bodies, event payloads, stack
traces or full logs, working-directory/host/user paths, shell commands, PIDs,
source diffs/Git remote metadata, private contacts/channel handles, raw
lock/lease details, or unbounded task/card text. A field enters the record
only with a documented consumer value, a bounded size/domain, and a clear
owner/clock.

Daemon self-records MUST be written on every daemon turn — every write that
already replaces `daemon.json`'s live state (turn bump, tool dispatch, CLI
output/usage accumulation, terminal markers) — through one chokepoint
(`DaemonRunDir._persist_daemon_state`), not a second scattered set of call
sites that could drift out of sync with `daemon.json` itself. A daemon
self-record MUST NOT carry task text, tool arguments, error messages, or any
path — only bounded identity (`run_id`/`handle`/`group_id`/`backend`),
lifecycle (`state`/`started_at`/`finished_at`/`turn`/`tool_call_count`), and
usage counters (`tokens`, `cli_tokens`).

Aggregation (`aggregate_daemon_records`) MUST scan only
`<working_dir>/daemons/*/session_stats.json`, sort newest-mtime-first, and
read at most `session_stats_daemon_limit()` (default 1000, environment
`LINGTAI_SESSION_STATS_DAEMON_LIMIT`) of them. A daemon run directory without
this file MUST be excluded from `scanned`/`counts_by_state`/`usage` — it MUST
NOT fall back to reading `daemon.json`, MUST NOT be inferred from directory
presence alone, and MUST NOT be represented as a zero-usage entry. `present`
reports the total number of daemon self-records that exist (before bounding),
so a consumer can tell "no daemons" apart from "more daemons than the bound."

The Agent record's own write is throttled by `session_stats_refresh_seconds()`
(default 5s, environment `LINGTAI_SESSION_STATS_REFRESH_SECONDS`) via
`should_refresh_agent_record`; the first write (no prior timestamp) and any
wall-clock regression always refresh. This throttle exists because the Agent
record's own refresh re-scans the bounded daemon set; it does not apply to
daemon self-record writes, which remain per-turn and unthrottled. Both
environment variables MUST validate with a safe fallback (missing, blank,
non-numeric, non-finite, zero, or negative values fall back to the documented
default) and MUST be documented in `ENVIRONMENT_VARIABLES.md`.

Core (`BaseAgent`) owns identity/session/health/usage/daemon-aggregate
fields built only from data it already holds; it MUST NOT import MCP,
Telegram, or other integration-specific modules. `BaseAgent._build_agent_record_extra`
is the one extension point for `handles`/`integrations` and returns `{}` by
default; `lingtai.Agent` overrides it to safelist verified handles (e.g. a
Telegram bot username) and MCP integration labels from
`services.mcp_registry`, mirroring the established `_build_manifest` override
pattern rather than inventing a second composition mechanism (a callback
attribute, a service locator, or a hidden Core import).

## Shapes

Agent record (`system/agent_record.json`, schema
`lingtai.agent_record/v1`): `schema`, `schema_version`, `generated_at`,
`sequence` (process-local monotonic, not a durability guarantee); `identity`
(`agent_id`, `agent_name`, `nickname`, `mail_address` — never the filesystem
working-directory path); `model` (provider/model/context_limit/service_tier,
the same safelist `_safe_llm_from_service` already enforces for
`.agent.json`); `handles` (flat string map, e.g. `{"telegram": "botuser"}`);
`integrations` (list of `{name, transport, connected}`); `session`
(`state`, `started_at`, `uptime_seconds`, `molt_count`); `health`
(`heartbeat_at`, `heartbeat_age_seconds`, `liveness` — `fresh`/`stale`/
`unknown` using the shared `HEARTBEAT_LIVENESS_SECONDS` threshold from
`kernel/agent_presence`'s contract, `last_api_call_at`, `last_progress_at`);
`usage` (`api_calls`, `input_tokens`, `output_tokens`, `thinking_tokens`,
`cached_tokens`, `context_used_tokens`, `context_limit_tokens`,
`context_usage_pct`, `context_system_tokens`, `context_tools_tokens`,
`context_history_tokens`); `daemons` (`present`, `scanned`, `limit`,
`counts_by_state`, `usage`).

Daemon self-record (`<run_dir>/session_stats.json`, schema
`lingtai.daemon_record/v1`): `schema`, `schema_version`, `generated_at`,
`run_id`, `handle`, `group_id`, `backend`, `state`, `started_at`,
`finished_at`, `turn`, `tool_call_count`, `tokens`
(`input`/`output`/`thinking`/`cached` — the kernel-ledger-feeding counters),
`cli_tokens` (`input`/`output`/`thinking`/`cached`/`calls` — external-CLI
display-only usage, kept distinct from `tokens` because it never touches
either token ledger, matching `DaemonRunDir.record_cli_tokens`'s existing
separation). Aggregation combines the two into one display total; neither
this module nor its aggregation ever writes to a token ledger.

## Contract rules

1. `system/agent_record.json` and `<run_dir>/session_stats.json` are written
   only via `write_agent_record`/`write_daemon_record`, both atomic through
   `kernel._fsutil.atomic_write_json`.
2. `BaseAgent._write_session_stats_record` is called from the same three
   hooks as `_write_status_snapshot` (`_save_chat_history`, the
   ACTIVE-without-progress watchdog, `_write_heartbeat_tick`) and is
   independently best-effort: a failure is logged and never interrupts the
   turn or the `.status.json`/manifest writes beside it.
3. `DaemonRunDir._persist_daemon_state` replaces every direct
   `self._atomic_write_json(self.daemon_json_path, self._state)` call; the
   daemon self-record write is best-effort and must never turn a successful
   `daemon.json` write into a failed one.
4. `aggregate_daemon_records` never raises on a missing `daemons/` directory,
   an unreadable run directory, or a corrupt/mismatched-schema self-record —
   it skips and continues; `present` still counts the file's existence even
   when its content is unreadable at the time of the scan (a subsequent read
   error only removes it from `scanned`, not from `present`, since a
   subsequent write could make it readable again).
5. `lingtai.Agent._build_agent_record_extra` reads only already-redacted,
   already-public sources (`mcp_registry.read_registry`/`read_identities`,
   the same allowlist the system prompt itself renders) and returns `{}` on
   any failure rather than raising.
6. Migrated consumers (`TelegramManager`'s Task Card footer,
   `LocalCommandCore.collect_kanban_data`) read only `read_agent_record`; they
   MUST NOT reintroduce a `.status.json`/heartbeat/token-ledger read on this
   path. `LocalCommandCore.collect_kanban_data`'s per-child token totals now
   reflect the child's current-session usage (the record's `usage` block),
   not a raw lifetime `token_ledger.jsonl` scan — an intentional migration,
   not an oversight; a historical/lifetime view remains available through the
   existing ledger-reading tools, unchanged by this contract.

## Contract tests

`tests/test_session_stats.py` locks: atomic-write behavior (temp-sibling +
`os.replace`, no partial reads) for both record types; `schema`/
`schema_version`/`generated_at` presence; the Agent-record redaction
allowlist (no working-dir path, no secrets, no prompts); `should_refresh_agent_record`'s
throttle/first-write/backwards-clock behavior; `session_stats_refresh_seconds`/
`session_stats_daemon_limit` fallback on missing/blank/non-numeric/zero/
negative values; `aggregate_daemon_records`'s bounded newest-first scan,
present-vs-scanned distinction, and silent-ignore of a daemon without a
self-record (no legacy `daemon.json` fallback, no fabricated zero). Daemon
per-turn writer behavior (one write of `daemon.json` produces one matching
`session_stats.json`) is proven alongside the existing `bump_turn`/
`set_current_tool`/`mark_done` coverage in `tests/test_daemon_run_dir.py`.
`tests/test_architecture_documents.py` enforces the governed twin, heading
order, canonical maintenance, and reciprocal links.

## Maintenance

Read the paired Anatomy for locations and composition. The projector,
`BaseAgent`'s hooks, `DaemonRunDir`'s chokepoint, migrated consumers, contract
tests, and this contract change together. A breaking record-shape change
bumps `contract_version`; implementation drift is a defect, not permission to
weaken this contract.

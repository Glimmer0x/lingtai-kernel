---
name: sqlite-log-query
description: >
  Nested system-manual reference for inspecting LingTai runtime traces through
  the additive SQLite/log.sqlite sidecar. Read via the `system-manual` router
  when you need `lingtai-agent log doctor|query|rebuild`, JSONL source-of-truth
  rules, read-only SQL safety, offline rebuild/WAL caveats, events,
  chat_entries, and token_entries schema, daemon/chat-history/token-ledger
  indexing, query recipes, runtime problem investigation workflow, trajectory
  mining workflow, SQL-based event
  metrics, cheap-model/daemon strategy, finding schema, prompt templates,
  digest output, or log redaction pitfalls. This is a nested skill-reference
  under `system-manual`, not a standalone catalog skill; its folder may carry
  companion scripts and assets as SQLite trace tooling grows.
version: 1.2.1
tags: [lingtai, system-manual, sqlite, log.sqlite, runtime-logs, trace, jsonl, daemon, trajectory, mining, event-log, improvement, pitfalls, observability, cheap-model]
last_changed_at: 2026-07-19T00:00:00Z
related_files:
- src/lingtai/intrinsic_skills/system-manual/SKILL.md
- src/lingtai/intrinsic_skills/system-manual/reference/sqlite-log-query/scripts/event_summary.py
maintenance: |
  Tracks the sqlite-log-query topic it documents; update when that integration changes.
---

# SQLite Log Query

LingTai keeps durable runtime traces and token ledgers in JSONL files. The SQLite file at
`logs/log.sqlite` is an **additive, rebuildable query index** over those JSONL
sources of truth. Use it to answer questions that are painful with `grep`: which
event types are hottest, what happened inside daemon runs, what chat-history
turn surrounded a failure, whether notification/daemon/context events are
storming, or how token usage is distributed across main/soul/daemon sources.

This reference also covers **trajectory mining** — the systematic process of
turning LingTai runtime event streams into actionable lessons for improving
LingTai itself. Trajectory mining starts from the SQLite log sidecar and uses
SQL queries as the primary data access layer.

## Safety contract

- **JSONL is authoritative.** `logs/log.sqlite` is derived; deleting it should not
  delete facts.
- **Prefer the CLI.** Use `lingtai-agent log ...` instead of opening the DB for
  writes yourself.
- **Queries are read-only with respect to SQLite database contents.** `log query` accepts read-only
  `SELECT`, CTE (`WITH ... SELECT`), and `EXPLAIN` statements and opens the sidecar through the
  kernel read-only inspection path. `query` and `doctor` preserve the main database mtime; ordinary
  live-safe SQLite `mode=ro` may create or update SQLite read-support `-wal`/`-shm` sidecar files as
  needed.
- **Rebuild is offline.** `log rebuild` requires the agent working-directory lock;
  if the agent is running, stop/sleep/lull/suspend it first as appropriate.
- **Runtime SQLite is best effort.** New top-level `logs/events.jsonl` and
  standard `logs/token_ledger.jsonl` rows are indexed live after the JSONL write
  succeeds. Chat history, archive, and daemon JSONL sources are indexed into a
  target agent sidecar by explicit offline rebuild so normal turns and daemon
  runs do not pay recursive scan or live-rewrite costs.
- **Live queries are snapshots.** Runtime writes use SQLite WAL mode. For a complete historical
  snapshot, stop the agent and run `log rebuild` before querying.
- **Never paste secrets.** Logs and chat history can contain URLs, tokens,
  prompts, and user data. Redact before sharing.

## Commands

Set a variable for the target agent directory:

```bash
AGENT_DIR=/path/to/project/.lingtai/agent-name
```

Check whether the sidecar exists and is readable:

```bash
lingtai-agent log doctor "$AGENT_DIR"
```

If `doctor` reports `{"status":"missing"...}` or the sidecar is stale/corrupt,
rebuild **only while the target agent is stopped/offline**:

```bash
lingtai-agent log rebuild "$AGENT_DIR"
```

`log rebuild` scans the known JSONL trace surfaces under the target agent:

- `logs/events.jsonl` → `events` (`source_kind='agent_events'`)
- `logs/token_ledger.jsonl` → `token_entries` (`source_kind='agent_token_ledger'`)
- `history/chat_history.jsonl` → `chat_entries` (`source_kind='agent_chat'`)
- `history/chat_history_archive.jsonl` → `chat_entries` (`source_kind='agent_chat_archive'`)
- `daemons/*/logs/events.jsonl` → `events` (`source_kind='daemon_events'`, `run_id=<daemon folder>`)
- `daemons/*/logs/token_ledger.jsonl` → `token_entries` (`source_kind='daemon_token_ledger'`, `run_id=<daemon folder>`)
- `daemons/*/history/chat_history.jsonl` → `chat_entries` (`source_kind='daemon_chat'`, `run_id=<daemon folder>`)

Run a read-only query:

```bash
lingtai-agent log query "$AGENT_DIR" \
  'SELECT id, ts, type, agent_address, substr(fields_json, 1, 240) AS fields
   FROM events
   ORDER BY ts DESC
   LIMIT 20'
```

The CLI prints JSON. Pipe to `jq` when available:

```bash
lingtai-agent log query "$AGENT_DIR" \
  'SELECT type, COUNT(*) AS n FROM events GROUP BY type ORDER BY n DESC LIMIT 20' \
  | jq .
```

## Schema quick reference

`events` indexes top-level agent runtime events and daemon run events:

| Column | Meaning |
|---|---|
| `id` | SQLite row id, not a stable cross-rebuild event identifier |
| `ts` | event timestamp as a numeric epoch-like value; ISO strings are parsed when possible |
| `type` | event `type` field, or daemon `event` field |
| `agent_address` | event `address` field when present |
| `agent_name_snapshot` | event `agent_name` field when present |
| `fields_json` | the remaining event fields as JSON text |
| `source_file` | JSONL file imported from |
| `source_offset` | byte offset in the JSONL source; unique with `source_file` |
| `source_line` | 1-based JSONL line number |
| `source_kind` | `agent_events`, `daemon_events`, or fallback kind |
| `scope` | `agent`, `daemon`, or `unknown` |
| `run_id` | daemon run folder name for daemon rows |
| `inserted_at` | sidecar insertion time |

`chat_entries` indexes agent and daemon chat-history JSONL rows:

| Column | Meaning |
|---|---|
| `id` | SQLite row id, not stable across rebuilds |
| `ts` | parsed numeric timestamp when a row has `ts`/`timestamp`, else `0` |
| `ts_text` | original timestamp text/value as stored in JSONL |
| `role` | chat role (`user`, `assistant`, etc.) when present |
| `kind` | LingTai daemon user-entry kind (`task`, `tool_results`, `followup`) when present |
| `turn` | daemon turn number when present |
| `content_text` | best-effort extracted plain text from `text` or content blocks |
| `entry_json` | full source chat row as JSON text |
| `source_file`, `source_offset`, `source_line` | source JSONL identity |
| `source_kind` | `agent_chat`, `agent_chat_archive`, `daemon_chat`, or fallback kind |
| `scope` | `agent`, `daemon`, or `unknown` |
| `run_id` | daemon run folder name for daemon rows |
| `inserted_at` | sidecar insertion time |

`token_entries` indexes agent and daemon token-ledger JSONL rows:

| Column | Meaning |
|---|---|
| `id` | SQLite row id, not stable across rebuilds |
| `ts` | parsed numeric timestamp when possible |
| `ts_text` | original `ts` value from JSONL |
| `input_tokens`, `output_tokens`, `thinking_tokens`, `cached_tokens` | token counters from the JSONL ledger row |
| `model`, `endpoint` | model/provider endpoint metadata when present |
| `source` | ledger source tag such as `main`, `soul`, `daemon`, `tc_wake`, or legacy/null |
| `em_id`, `run_id`, `api_call_id` | daemon/run/API attribution when present |
| `entry_json` | full source token-ledger row as JSON text |
| `source_file`, `source_offset`, `source_line` | source JSONL identity |
| `source_kind` | `agent_token_ledger`, `daemon_token_ledger`, or fallback kind |
| `scope` | `agent`, `daemon`, or `unknown` |
| `inserted_at` | sidecar insertion time |

Parent ledgers intentionally include daemon spend rows. If you query both
`agent_token_ledger` and `daemon_token_ledger` rows together, avoid double-counting
daemon calls that were mirrored into the parent ledger and the daemon-local ledger.
Filter by `source_kind`, `source`, `em_id`, or `run_id` according to the report you
need.

Maintenance tables:

- `schema_migrations(version, name, applied_at)` records sidecar schema version.
- `import_cursors(source_file, byte_offset, line_no, updated_at)` records the last
  rebuild/import cursor for each JSONL source.

## Query recipes

Recent events:

```sql
SELECT id, ts, type, source_kind, run_id, substr(fields_json, 1, 300) AS fields
FROM events
ORDER BY ts DESC
LIMIT 50;
```

Event type counts across agent + daemon events:

```sql
SELECT source_kind, type, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts
FROM events
GROUP BY source_kind, type
ORDER BY n DESC
LIMIT 50;
```

Recent chat-history entries:

```sql
SELECT id, source_kind, run_id, role, kind, turn, substr(content_text, 1, 400) AS text
FROM chat_entries
ORDER BY id DESC
LIMIT 50;
```

Join daemon tool events with daemon chat rows by `run_id`:

```sql
SELECT e.run_id, e.ts, e.type, json_extract(e.fields_json, '$.name') AS tool,
       c.role, c.turn, substr(c.content_text, 1, 240) AS chat
FROM events e
LEFT JOIN chat_entries c ON c.run_id = e.run_id AND c.turn = json_extract(e.fields_json, '$.turn')
WHERE e.source_kind = 'daemon_events'
ORDER BY e.ts DESC
LIMIT 100;
```

Search for errors or failures:

```sql
SELECT id, ts, source_kind, run_id, type, substr(fields_json, 1, 500) AS fields
FROM events
WHERE lower(type) LIKE '%error%'
   OR lower(type) LIKE '%fail%'
   OR lower(fields_json) LIKE '%error%'
   OR lower(fields_json) LIKE '%traceback%'
ORDER BY ts DESC
LIMIT 100;
```

Look for notification storms:

```sql
SELECT type, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts
FROM events
WHERE type LIKE 'notification%'
   OR fields_json LIKE '%notification%'
GROUP BY type
ORDER BY n DESC;
```

Search chat-history text:

```sql
SELECT source_kind, run_id, role, turn, substr(content_text, 1, 500) AS text
FROM chat_entries
WHERE lower(content_text) LIKE '%sqlite%'
ORDER BY id DESC
LIMIT 100;
```

Token usage by ledger source kind:

```sql
SELECT source_kind, source,
       COUNT(*) AS calls,
       SUM(input_tokens) AS input_tokens,
       SUM(output_tokens) AS output_tokens,
       SUM(thinking_tokens) AS thinking_tokens,
       SUM(cached_tokens) AS cached_tokens
FROM token_entries
GROUP BY source_kind, source
ORDER BY input_tokens DESC;
```

Main-agent token usage without daemon rows from the parent ledger:

```sql
SELECT COUNT(*) AS calls,
       SUM(input_tokens) AS input_tokens,
       SUM(output_tokens) AS output_tokens,
       SUM(thinking_tokens) AS thinking_tokens,
       SUM(cached_tokens) AS cached_tokens
FROM token_entries
WHERE source_kind = 'agent_token_ledger'
  AND COALESCE(source, '') != 'daemon'
  AND em_id IS NULL
  AND run_id IS NULL;
```

Inspect one event's full JSON payload:

```sql
SELECT id, type, fields_json
FROM events
WHERE id = 123;
```

Use SQLite JSON functions when available:

```sql
SELECT
  type,
  json_extract(fields_json, '$.tool') AS tool,
  json_extract(fields_json, '$.error') AS error
FROM events
WHERE fields_json LIKE '%error%'
ORDER BY ts DESC
LIMIT 50;
```

If JSON functions are unavailable in the local SQLite build, fall back to
`fields_json LIKE ...` and inspect the returned JSON text.

## Source discovery

Before trajectory mining, discover what data exists in the sidecar. The
sidecar replaces the old `find`-based JSONL scanning with SQL:

```sql
-- What sources were imported?
SELECT source_kind, source_file, COUNT(*) AS n
FROM events
GROUP BY source_kind, source_file
ORDER BY n DESC;
```

```sql
-- Schema discovery: what keys appear in fields_json?
SELECT json_each.key, COUNT(*) AS n
FROM events, json_each(events.fields_json)
GROUP BY json_each.key
ORDER BY n DESC
LIMIT 30;
```

```sql
-- What source families are present?
SELECT scope, source_kind, COUNT(*) AS n,
       MIN(ts) AS earliest, MAX(ts) AS latest
FROM events
GROUP BY scope, source_kind
ORDER BY n DESC;
```

### Key source families

| Family | Typical source_kind | Primary signal |
|--------|---------------------|----------------|
| Agent event log | `agent_events` | tool calls, tool results, errors, context pressure |
| Daemon event log | `daemon_events` | task lifecycle, timeouts, exits |
| Agent chat | `agent_chat` / `agent_chat_archive` | turn-level conversation |
| Daemon chat | `daemon_chat` | daemon task interactions |

## Workflow: investigate a suspected runtime problem

1. Identify the agent directory. If unsure, use the `.lingtai/<agent>` directory
   shown in the agent's identity/pad or ask the orchestrator.
2. Stop the target agent if exact complete history matters, then run
   `lingtai-agent log rebuild "$AGENT_DIR"`. Otherwise begin with `doctor` and
   live event queries.
3. Start broad: event/source-kind counts and recent rows.
4. Narrow by time/type/text. Include `source_kind` and `run_id` in queries when
   daemon evidence matters.
5. Cross-check surprising findings against source JSONL (`logs/events.jsonl`,
   `history/chat_history*.jsonl`, daemon subdirectories) before filing bugs or
   making claims.
6. When reporting, quote minimal evidence and redact secrets.

---

## Trajectory Mining

Use **trajectory mining** when the human asks to mine, analyze, or audit LingTai
agent logs, scan for patterns, or generate improvement candidates from runtime
traces. It is a cheap, systematic pre-pass over `log.sqlite` that turns
operational pitfalls into knowledge/skill/issue candidates. Do **not** use it
for quick chat-history summaries, code review, or feature planning.

### Pipeline (10 steps, condensed)

1. **Ground the ask** — clarify scope (time window, agent, source families, the
   question).
2. **Check data** — `lingtai-agent log doctor`; note WAL/live-read caveats (see
   Safety contract).
3. **Manifest** — decide the event universe (source kinds, run_ids, time bounds)
   and stick to it.
4. **Mechanical first-pass (SQL only)** — run aggregation queries: event counts
   by `source_kind`, cache-rate/token patterns, tool-result spill, error
   clusters, chunking/slicing windows. Never pass raw logs to an LLM.
5. **Chunk and redact** — slice by source family / time window; apply the
   Redaction rules below before any LLM call.
6. **Dispatch cheap daemon batch** — one daemon per slice using the cheapest
   adequate preset; the primary agent never digests raw traces.
7. **Primary-agent triage** — merge findings, validate each against reproducible
   SQL evidence, drop weak or unverifiable ones.
8. **Produce digest** — high-signal findings, quick wins, issue candidates,
   observability gaps, no-action observations, evidence appendix, next steps.
9. **Route outputs** — propose routing (skill/knowledge/issue/patch); wait for
   human approval before any side effect.
10. **Stop** — a good digest lets the human choose: update skill, file issue,
    patch, ignore, or schedule.

**Model discipline**: first-pass metrics are pure SQL (no LLM). LLM passes use
the cheapest adequate model (tier-1/tier-2) for classification and anomaly
summarization; the primary agent does synthesis and judgment.

**Validation**: a finding is only reportable if a SQL query can reproduce it;
separate high-signal findings from observability gaps (things the logs cannot
yet show).

**Periodic mode**: mining can run on a schedule, but each run must produce a
fresh digest and side effects stay human-gated.

## Redaction and privacy rules

Apply these in order, before any LLM call:

1. **Redact tokens and credentials**: replace any value matching
   `(token|key|secret|password|credential|oauth)[":=\s]+[^\s",]{8,}` with
   `[REDACTED]`.
2. **Redact message bodies**: if an event field contains human-written message
   text, summarize rather than quote unless exact wording is necessary for the
   finding.
3. **Redact file paths containing usernames**: replace `/Users/<name>/` with
   `/Users/[USER]/`.
4. **Redact IP addresses and internal hostnames**: replace with `[HOST]`.
5. **Quote minimum evidence**: cite event type, timestamp/line range, and
   redacted field names. Do not dump entire event objects.
6. **No side effects without approval**: the output of trajectory mining is a
   recommendation digest. Do not create files, issues, commits, PRs, scheduled
   jobs, or agent refreshes.

## Pitfalls

Beyond the safety contract above:

- Do not treat `log.sqlite` as a coordination database. It is an observability
  index, not agent state.
- Do not rebuild a live agent by bypassing the CLI lock; that risks racing the
  runtime logger.
- Do not share raw `fields_json` or `entry_json` blindly; they may contain private
  content.
- Do not assume `id` survives rebuilds. Use `source_file/source_offset`, time,
  `run_id`, and surrounding context for durable references.
- If a query returns fewer rows than expected on a live agent, remember the WAL
  snapshot and explicit-rebuild caveats; stop/rebuild or inspect JSONL.

## Scripts

### event_summary.py

A standalone Python script that summarizes a LingTai `log.sqlite` file. It reads
database contents without modifying them, makes no network requests, and requires
no secrets. SQLite may create or update read-support `-wal`/`-shm` sidecars.

```bash
# Summarize all events in the sidecar
python3 scripts/event_summary.py "$AGENT_DIR/logs/log.sqlite"

# Limit to last 24 hours
python3 scripts/event_summary.py "$AGENT_DIR/logs/log.sqlite" --hours 24

# Output as compact JSON
python3 scripts/event_summary.py "$AGENT_DIR/logs/log.sqlite" --format json

# Filter to a specific source kind
python3 scripts/event_summary.py "$AGENT_DIR/logs/log.sqlite" --source-kind daemon_events
```

The script outputs: event type counts, tool call summaries, error clusters,
latency gap analysis, source kind breakdown, time range, and schema key
discovery — all via read-only SQL queries.

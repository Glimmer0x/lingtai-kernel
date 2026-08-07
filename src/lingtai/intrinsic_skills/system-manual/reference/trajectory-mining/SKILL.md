---
name: trajectory-mining
description: >
  Nested system-manual reference for trajectory mining — turning LingTai runtime
  event streams into validated, actionable improvement candidates. Read this
  after `reference/sqlite-log-query/SKILL.md` has given you the data access
  layer: manifest policy, cheap-model/daemon strategy, prompt templates, the
  finding schema and confidence rubric, the digest template, output routing, and
  periodic mode.
version: 1.0.0
last_changed_at: "2026-08-07T00:00:00Z"
tags: [lingtai, system-manual, trajectory, mining, improvement, digest, findings, observability, cheap-model, daemon, audit]
related_files:
- src/lingtai/intrinsic_skills/system-manual/SKILL.md
- src/lingtai/intrinsic_skills/system-manual/reference/sqlite-log-query/SKILL.md
maintenance: |
  Workflow/process node. The SQLite sidecar schema, the CLI commands, the SQL
  recipes, and the redaction rules are owned by
  `reference/sqlite-log-query/SKILL.md` — cite them, do not restate them here.
  Update when the finding schema, the confidence rubric, the digest template, or
  the routing destinations change.
---

# Trajectory Mining

Trajectory mining is the systematic process of turning LingTai runtime event
streams into actionable lessons for improving LingTai itself. It starts from the
SQLite log sidecar and uses SQL as the primary data access layer.

**Prerequisite reading:** `reference/sqlite-log-query/SKILL.md` owns the data
layer — `lingtai-agent log doctor|query|rebuild`, the
`events`/`chat_entries`/`token_entries` schema, source discovery, the mechanical
first-pass metric and slicing queries, and the canonical redaction rules. This
node owns only the workflow built on top of it.

## When to use / when not to use

**Use trajectory mining when:**
- The human asks to mine, analyze, or audit LingTai event logs.
- The human says something like "最近轨迹", "look at my agent logs", "what went
  wrong last session", "scan for patterns", or "generate improvement candidates".
- You need to systematically extract operational pitfalls from large structured
  traces before writing a knowledge entry, skill, or issue draft.
- You want to build a cheap pre-pass before involving expensive models.

**Do not use trajectory mining when:**
- The human just wants a quick summary of chat history without event-log grounding.
- The request is about code review, architecture analysis, or feature planning
  unrelated to runtime traces.
- You already have a specific, pre-identified bug and just need to fix it — skip
  the mining phase and go directly to debugging.

## Manifest building

After source discovery, build a manifest before any LLM review. The manifest is
your contract for what you will and will not read:

```text
source_kind | source_file | n | time_range | top_types | why_included
```

Keep the manifest in memory (or a temp file) — do not persist private log paths
to shared storage.

**Limits:**
- Default window: last 24 hours or current workstream. Never scan everything
  unless explicitly asked.
- Maximum lines to feed any single LLM call: 300 lines of redacted excerpts.
- If a result set exceeds 5000 rows, use time-window or event-family slicing
  (queries in sqlite-log-query → "Metrics and slicing recipes").

## Cheap model / daemon strategy

### Model selection priority

Work up from the cheapest surface that can do the job; the concrete adapter and
preset names available to you are owned by
`reference/llm-adapters/SKILL.md` and `system(action="presets")`.

| Tier | When to use |
|---|---|
| Cheapest available model | Large-volume classification, error clustering, first-pass anomaly detection |
| Cheap structured-output model | Structured YAML extraction from moderate excerpts |
| Mid-tier model | Pattern matching over aggregated metrics; moderate-complexity finding synthesis |
| Primary agent model (this session) | Shortlist triage, finding merging, confidence adjudication |
| Frontier model | Only for ambiguous high-impact architecture/design findings |

**Default: never reach the frontier tier unless the human explicitly approves the
budget.**

### Daemon task structure

Spawn one daemon task per (source family × time window). Keep each task small:

- Input: redacted aggregate metrics + bounded excerpts (≤300 lines)
- Output: structured YAML only, using the finding schema below
- No side effects inside the daemon

Example daemon task description:

```text
Analyze these LingTai event-log excerpts (source: <family>, window: <time range>).
Extract durable runtime improvement candidates visible in the event data.
Focus on: tool failures, latency gaps, context pressure, daemon lifecycle, auth/env issues, observability gaps.
Do NOT quote secrets, tokens, or full message bodies. Redact paths if they contain usernames or private data.
Output ONLY a YAML list using this schema: [id, category, severity, confidence, event_evidence, pattern, impact, suggested_destination, suggested_next_step, side_effect_required].
Prefer 3-5 high-signal findings over a long list of weak ones.
```

### Parallel dispatch strategy

When multiple source families or time windows exist, dispatch them in parallel:

```
daemon-1: agent_events — tool_call/tool_result family — last 24h
daemon-2: daemon_events — lifecycle family — last 7d
daemon-3: agent_chat — turn timing family — last 24h
daemon-4: context/spill events — pressure family — last 7d
```

Collect all results before primary-agent triage.

## Prompt templates

Each template below expects redacted input and returns YAML only — no prose
before or after the YAML block.

### Classifier prompt

```
You are a runtime event log classifier for a multi-agent system called LingTai.
Below is a redacted aggregate summary of event-log metrics from a single source family and time window.
Classify the top patterns you see into the following categories:
  tool-failure, latency, context-pressure, daemon-lifecycle, auth-env, observability-gap, doc-gap, missing-skill, bug-candidate, process-improvement

For each category you identify, output one YAML block:
  category: <category>
  evidence_summary: <1-2 sentences citing event types, counts, or timing — no secrets>
  confidence: low | medium | high

METRICS:
{metrics_block}
```

### Anomaly summarizer prompt

```
You are analyzing a bounded excerpt from a LingTai agent event log.
The excerpt is centered on a suspicious event. Surrounding lines are provided for context.
Your task: summarize the anomaly in terms of what failed, why it likely failed (based on event data only), and what the downstream impact was.

Rules:
- Do not quote tokens, credentials, or full message bodies.
- Reference events by their type, timestamp offset, and redacted field names.
- Output YAML only:
  anomaly_type: <one of: tool-failure | latency-spike | context-overflow | daemon-exit | auth-failure | unknown>
  timeline: <ordered list of key events in the excerpt>
  root_cause_hypothesis: <1 sentence, hedged>
  downstream_impact: <1 sentence>
  confidence: low | medium | high

EXCERPT (redacted):
{excerpt_block}
```

### Observability-gap prompt

```
You are reviewing LingTai event-log summaries to identify what information is MISSING that would be needed to diagnose operational problems.
You have seen: {event_types_present}.
You did NOT see (or saw too rarely): {event_types_sparse}.

For each significant gap, output YAML:
  gap: <what is missing>
  why_needed: <what class of problem it would help diagnose>
  suggested_event: <what event type or field would close the gap>
  priority: low | medium | high
```

### Cross-run pattern prompt

```
You are comparing event-log aggregate summaries from multiple LingTai sessions or agents.
Each summary is labeled with its source (agent name or daemon ID) and time window.
Identify patterns that repeat ACROSS multiple sources/sessions, not just within one.

For each cross-run pattern, output YAML:
  pattern_id: <short slug>
  description: <what repeats and where>
  sources_affected: [list of source labels]
  recurrence_count: <approximate>
  severity: low | medium | high
  confidence: low | medium | high

SUMMARIES:
{summaries_block}
```

## Finding schema

Every finding, from any daemon or primary-agent review, must fit this schema:

```yaml
- id: short-stable-slug              # kebab-case, unique within the digest
  category: tool-failure | latency | context-pressure | daemon-lifecycle | auth-env | observability-gap | doc-gap | missing-skill | bug-candidate | process-improvement
  severity: low | medium | high
  confidence: low | medium | high
  event_evidence:
    - source: local path or source_file value
      line_or_time: line number, Unix timestamp, ISO timestamp, or event id
      event_type: tool_call | tool_result | notification | daemon_state | context_pressure | other
      redacted: true | false
      note: short redacted quote or paraphrase of the event content
  optional_context:
    - source: path, URL, or issue reference
      note: why this corroborates the event-log signal
  pattern: what repeated or what caused harm — describe in event terms
  impact: why it matters to LingTai, users, or agents
  suggested_destination: knowledge | skill | issue-draft | code-investigation | observability-improvement | no-action
  suggested_next_step: smallest concrete next action
  side_effect_required: none | human-approval-required
```

A finding needs at least one `event_evidence` entry with a verifiable source and
line/time, and its `pattern` must describe something visible in event data, not
inferred from chat history alone.

## Validation and confidence rubric

Before finalizing any finding:

1. **Re-read the source data**: confirm the source_file, source_line, or time
   range are accurate, and that timestamps form a plausible causal sequence.
2. **Check recurrence**: re-query for similar events across the full time window
   and note the count.
3. **Reject hallucinated fields**: if a daemon output references event fields
   that do not exist in the actual schema discovered in source discovery, discard
   or flag that finding.

| Evidence | Confidence |
|----------|-----------|
| ≥3 occurrences of the same event pattern, confirmed in source file | high |
| 2 occurrences OR 1 occurrence + corroborating optional_context | medium |
| 1 occurrence, no corroboration, no impact confirmed | low |
| Inferred from absence of events only | low |
| Daemon output references field not found in actual schema | reject |

A single occurrence of an error with no pattern context is `severity: low` and
`confidence: low` unless that single event had confirmed high impact (e.g. the
agent stopped functioning) — otherwise exclude it.

## Output digest template

Produce the digest in the agent's working language. Fields in brackets are
placeholders.

```
# 轨迹挖掘摘要 / Trajectory Mining Digest
Generated: [ISO timestamp]
Sources scanned: [source_kinds, total ~N events, time window]
Models used: [list of cheap models + primary agent]

---

## High-Signal Findings ([N])
severity high or medium, with high confidence.

[YAML block]

---

## Quick Wins ([N])
suggested_destination is knowledge, skill, or observability-improvement, and
side_effect_required is none.

[YAML block]

---

## Issue Candidates ([N])
side_effect_required: human-approval-required.

[YAML block]

---

## Observability Gaps ([N])
category: observability-gap — what was missing that would help future diagnosis.

[YAML block]

---

## No-Action Observations ([N])
severity low or confidence low, retained for reference.

[YAML block]

---

## Evidence Appendix
[Table: finding_id | source_file | line_or_time | event_type | redacted_note]

---

## Recommended Next Steps
Choose one or more:
- [ ] Write/update skill: [skill name]
- [ ] Write knowledge entry: [topic]
- [ ] Draft issue for human review: [title]
- [ ] Code investigation: [component]
- [ ] Add observability: [event type / field]
- [ ] No action needed
```

## Routing next actions

After producing the digest, route durable outputs as follows:

| Finding type | Destination | Action |
|---|---|---|
| Reusable operational pattern | `skill` | Propose skill update; wait for human approval |
| Private operational fact about this deployment | `knowledge` | Write knowledge entry (no secrets) |
| Active task / in-progress investigation | `pad` | Update pad with bounded note |
| LingTai bug or design issue | Issue draft | Use `lingtai-issue-report` skill if available; **ask human approval before filing** |
| Code change needed | Local worktree/patch | Propose; do not apply without approval |
| Configuration change | Propose in digest | **Do not apply without approval** |
| No clear action | `no-action` | Note in digest; move on |

## Periodic mode

If the human wants recurring event-log mining:

- **Do not set any scheduler without explicit approval.** Ask the human to
  confirm the cadence and scope first.
- Default cadence when approved: daily digest, not continuous monitoring.
- The scheduled job should only wake the agent with a bounded prompt; the agent
  performs the review.
- The digest should be silent (written to `pad.md` or a report file) unless
  `standing-rules.md` allows periodic check-in messages.

Suggested scheduled prompt body (for human approval before use):

```text
Run trajectory mining on recent SQLite event traces for the last 24h.
Produce a concise digest of high-signal runtime pitfalls and improvement candidates.
Do not create issues, commits, PRs, config changes, or scheduled jobs without explicit human approval.
Write the digest to: reports/trajectory-digest-YYYYMMDD.md
```

## Concrete example findings

### Example A: stale Claude Code OAuth token

```yaml
- id: stale-claude-code-oauth-token
  category: auth-env
  severity: high
  confidence: high
  event_evidence:
    - source: daemons/em-<id>/logs/events.jsonl
      line_or_time: "~line 847, ts 1716XXXXXX"
      event_type: tool_result
      redacted: true
      note: "claude CLI returned 'weekly limit reached'; subsequent tool_result showed success after env patch"
  optional_context:
    - source: "GitHub: Lingtai-AI/lingtai#189"
      note: confirmed stale inherited env token failure mode
  pattern: >
    Long-lived daemon inherits stale CLAUDE_CODE_OAUTH_TOKEN from parent env.
    After credential refresh, the env override prevents the new token from taking effect.
    Agents see 'weekly limit' errors and stop delegating heavy work.
  impact: Agents misdiagnose quota exhaustion; heavy work is not delegated.
  suggested_destination: code-investigation
  suggested_next_step: Strip stale env tokens in daemon backend env; add smoke test.
  side_effect_required: human-approval-required
```

### Example B: tool-result spill / context pressure

```yaml
- id: tool-result-spill-context-pressure
  category: context-pressure
  severity: medium
  confidence: medium
  event_evidence:
    - source: logs/events.jsonl
      line_or_time: "lines ~1200–1250"
      event_type: tool_result
      redacted: true
      note: "tool_result event has result_size > threshold; subsequent context_pressure event shows usage >85%"
  pattern: >
    Large tool results push context usage past 85%. The spill event appears but
    the agent continues without triggering molt early enough.
  impact: Tasks are interrupted or produce incomplete output; user must re-prompt.
  suggested_destination: observability-improvement
  suggested_next_step: Verify that spill events are routed to the molt trigger.
  side_effect_required: none
```

## On-demand procedure (step-by-step)

1. **Clarify window and scope.** Default: recent event logs for the current
   agent/project plus daemon events from the active workstream. "最近轨迹" →
   last 24h or current active workstream. Named subsystem → filter to it.
2. **Discover sources** (sqlite-log-query → "Source discovery") and build the
   manifest.
3. **Schema discovery** — sample keys via `json_each()` before writing any
   extraction code.
4. **Mechanical first-pass** — run the aggregation queries; do not pass raw logs
   to any LLM.
5. **Chunk and redact** — apply a slicing strategy, then sqlite-log-query's
   redaction rules.
6. **Dispatch cheap daemon batch** — one daemon per source family / time window.
7. **Primary-agent triage** — merge findings, validate against the confidence
   rubric.
8. **Produce digest** — render the template, include the evidence appendix.
9. **Route outputs** — propose routing; wait for human approval before any side
   effect.
10. **Stop.** A good digest gives the human enough to choose: update skill, file
    issue, make patch, ignore, or schedule.

---
name: system-manual
description: >
  Second-layer router for LingTai's progressive-disclosure operating manuals.
  Read this when resident substrate/procedures are too compact and you need the
  right lower reference; route from the table, then open that node.
version: 1.17.0
last_changed_at: "2026-08-27T00:00:00Z"
tags: [lingtai, agent, runtime, procedures, substrate, system, lifecycle, alarm, memory, communication, skills, settings, molt, summarize, nudge, updates, runtime-checks, refresh, preset, llm, adapters, codex, websocket]
related_files:
- src/lingtai/prompts/substrate/substrate.md
- src/lingtai/prompts/procedures/procedures.md
- src/lingtai/kernel/base_agent/lifecycle.py
- src/lingtai/tools/system/karma.py
- src/lingtai/tools/system/schema.py
- src/lingtai/tools/system/CONTRACT.md
- src/lingtai/tools/system/ANATOMY.md
- src/lingtai/tools/system/settings.py
- tests/test_system_declared_plugin.py
- src/lingtai/kernel/nudge/ANATOMY.md
- src/lingtai/intrinsic_skills/system-manual/reference/llm-adapters/SKILL.md
- src/lingtai/intrinsic_skills/system-manual/reference/external-attach-diagnostic/SKILL.md
- src/lingtai/llm/_register.py
- src/lingtai/llm/openai/adapter.py
- src/lingtai/intrinsic_skills/system-manual/reference/tool-plugin-settings/SKILL.md
- tests/test_skills.py
maintenance: |
  Tracks the routed source/resources it summarizes; update when the underlying capability or its sub-references change.
---

# System Manual — Progressive Disclosure Router

`system-manual` is the second layer of LingTai operating guidance. The resident
`substrate` and `procedures` prompts keep only the short rules every agent must
hold constantly. This skill routes from those compact rules to the reference node
that carries the actual detail.

Use this file first when the question is about LingTai's agent runtime, resident
prompt design, lifecycle, memory, communication, tool routing, system operations,
runtime trace inspection, runtime/kernel update checks, or nudge handling, then
open the lower node the router table names.


## Nested reference catalog

`system-manual` owns the nested skill-references below, so the router can
advertise lower nodes without promoting them to standalone top-level skills.
The router table is the routing authority; this list is the inventory.

```yaml
- name: substrate-manual
  location: reference/substrate-manual/SKILL.md
  description: |
    Expanded substrate/runtime model: body/extensions, lifecycle states,
    `system` actions (including last-resort `system.sleep(delay=...)` alarms),
    memory layers, MCP/addon ownership, preset tiers, and (§11) `init.json`
    composition and the preset runtime model.
- name: procedures-manual
  location: reference/procedures-manual/SKILL.md
  description: |
    Expanded action discipline: progressive disclosure, responsiveness,
    external side-effect authorization, the daemon workflow methodology,
    depositing work, idle/lifecycle, skill routing, deliverables, and issues.
- name: sqlite-log-query
  location: reference/sqlite-log-query/SKILL.md
  description: |
    SQLite/`log.sqlite` runtime trace inspection: `lingtai-agent log
    doctor|query|rebuild`, JSONL source-of-truth rules, read-only SQL safety,
    the events/chat_entries/token_entries schema, quick-start snippets, SQL
    recipes (`tool_call_id` lifecycle, tool result stats/percentiles, spilled
    results), gotchas, and redaction.
- name: trajectory-mining
  location: reference/trajectory-mining/SKILL.md
  description: |
    Trajectory/anomaly mining workflow built on sqlite-log-query: manifest
    policy, cheap-model daemon strategy, prompt templates, the finding schema
    and validation rubric, digest output, routing, and periodic mode.
- name: refresh-precheck
  location: reference/refresh-precheck/SKILL.md
  description: |
    Nested system-manual reference: the ordered pre-flight to run BEFORE
    `system(action="refresh")` (including preset swap/revert), the refresh
    sequence itself, and the post-refresh verification pass. Covers
    authorization boundary, allowed-preset catalog, MCP registry/init.json
    consistency, newly introduced env vars, context-vs-target-context_limit,
    durable-store and working-tree state, source_drift, and what to check when
    a refresh fails or comes back with a broken surface.
- name: runtime-update-checks
  location: reference/runtime-update-checks/SKILL.md
  description: |
    Kernel update/nudge lifecycle: runtime and source discovery,
    `kernel_version` and `source_drift`, heartbeat dispatch,
    `.notification/nudge.json`, packaged versus editable/source runtimes,
    installer ownership, refresh boundaries, and read-only diagnosis.
- name: environment-variables
  location: reference/environment-variables/SKILL.md
  description: |
    Router to the repo-root `ENVIRONMENT_VARIABLES.md` registry, which owns
    every LingTai environment variable's purpose, default, accepted values,
    scope, read point, reload behavior, and invalid-value handling.
- name: tool-plugin-settings
  location: reference/tool-plugin-settings/SKILL.md
  description: |
    Developer reference for one ToolFamily's optional SHOW-only settings provider.
- name: goal-manual
  location: reference/goal-manual/SKILL.md
  description: |
    Goal notifications: protected `.notification/goal.json` as the active-goal
    source of truth, `/goal` guided setup, idle goal reminders, and
    cancellation/completion semantics.
- name: how-to-change-name
  location: reference/how-to-change-name/SKILL.md
  description: |
    Changing a live agent workdir/address on POSIX: suspend, an atomic
    no-replace rename, and a verified resume.
- name: llm-adapters
  location: reference/llm-adapters/SKILL.md
  description: |
    Built-in LLM adapters: named adapter inventory, per-provider
    configuration/dispatch, the Codex REST vs WebSocket transport opt-in and
    its environment variables, and provider special behaviors.
- name: external-attach-diagnostic
  location: reference/external-attach-diagnostic/SKILL.md
  description: |
    Guarded macOS-only external attach: exact agent-dir/PID incarnation
    verification, bounded `/usr/bin/sample` stacks, content-free runtime facts,
    and an exceptional controlled external `mcp.*` burst that does not exercise
    Store locking.
```

## Router table

| Need / keywords | Read |
|---|---|
| Expanded substrate; body/extensions; shell vs daemon vs avatar vs MCP; lifecycle states; ACTIVE/IDLE/STUCK/ASLEEP/SUSPENDED; `system.sleep(delay=...)` last-resort alarm; same-channel communication; basic notifications; memory layers; molt model; idle/soul; preset tiers; `system` operations | `reference/substrate-manual/SKILL.md` |
| `init.json` composition/owner map; preset runtime model; raw vs resolved `system/manifest.resolved.json`; preset identity/path; TUI/library discovery vs `system(action="presets")` allowed-only catalog; main-agent swap/revert/refresh; daemon `tasks[].preset` explicit/omitted path; external CLI backend preset skip | `reference/substrate-manual/SKILL.md` §11 |
| Expanded procedures; progressive disclosure; writing skills/knowledge; action discipline; responsiveness; skill routing; HTML deliverables; artifact sharing; issue reporting; when to read which manual | `reference/procedures-manual/SKILL.md` |
| Tool-result summarization; large-result ranking via agent_meta; progressive disclosure of raw outputs; original-result recovery; summarize vs molt | `context-manual` → `reference/summarize-manual/SKILL.md` |
| SQLite; `log.sqlite`; LingTai runtime logs; runtime trace inspection; JSONL traces; `lingtai-agent log doctor`; `lingtai-agent log query`; `lingtai-agent log rebuild`; events/chat_entries schema; daemon/chat-history trace indexing; WAL/live-read caveats; SQL recipes; `tool_call_id` lifecycle; tool result stats and percentiles; spilled/large tool results | `reference/sqlite-log-query/SKILL.md` |
| Trajectory mining; trajectory/anomaly mining; improvement digests; finding schema and validation; cheap-model daemon strategy; mining prompt templates; periodic mining mode | `reference/trajectory-mining/SKILL.md` |
| Notifications; direct `notification(action='manual', input={})`; check/dismiss_channel/dismiss_event/dismiss_ref/manual; `.notification/<channel>.json`; channel allowlist; the top-level `instructions` field in the `.notification/<channel>.json` envelope; protected channels; generic vs producer dismiss; stale-version/force; legacy `large_tool_result` dismiss | `notification-manual` |
| About to call `system(action="refresh")`; preset swap/revert pre-flight; "will this refresh break something?"; refresh returned but MCP/tools/LLM look wrong; refresh failed | `reference/refresh-precheck/SKILL.md` |
| Kernel update lifecycle; runtime/source discovery; `kernel_version` and `source_drift`; heartbeat nudge dispatch; `.notification/nudge.json`; durable state; sync/wake/dismiss mechanics; packaged vs editable/source installs; refresh vs TUI-managed update; verification/troubleshooting | `reference/runtime-update-checks/SKILL.md` |
| Environment variables; Nudge controls; accepted values; read/reload behavior; invalid-value fallback; security cautions | `reference/environment-variables/SKILL.md` |
| Add or inspect a ToolFamily SHOW-only settings provider | `reference/tool-plugin-settings/SKILL.md` |
| Goal notifications; `.notification/goal.json`; active goal source of truth; goal `instructions`; idle goal reminder; cancel/complete goal | `reference/goal-manual/SKILL.md` |
| Change an agent workdir basename/address; POSIX suspend → no-replace rename → resume; preserve `agent_id` and true name | `reference/how-to-change-name/SKILL.md` |
| LLM adapters; named adapter inventory; provider configuration; Codex REST vs WebSocket transport; `LINGTAI_CODEX_TRANSPORT` / `LINGTAI_CODEX_WS` opt-in; provider special behaviors | `reference/llm-adapters/SKILL.md` |
| Authorized external attach; macOS `/usr/bin/sample`; exact PID/agent-dir incarnation verification; bounded content-free stacks; guarded controlled external `mcp.*` burst; diagnostic privacy | `reference/external-attach-diagnostic/SKILL.md` |
| Molt mechanics, pad tending, session journals, post-wipe recovery | `context-manual` |
| Soul tool; soul flow opt-in (`LINGTAI_SOUL_FLOW_ENABLED`); disabled-flow behavior; `delay_seconds` as cadence-not-off-switch; inquiry/config/voice/dismiss; privacy/cost rationale | `soul-manual` |
| Authoring/publishing skills or changing skill catalog behavior | `skills-manual` |
| Knowledge-entry layout and private durable memory | `knowledge-manual` |
| MCP registration/activation/addon ownership | `mcp-manual` |
| Bash/cron/host scheduling details | `shell-manual` |
| Daemon lifecycle/inspection/debugging | `daemon-manual` |
| Avatar spawning/management/escalation | `avatar-manual` |
| Kernel architecture/code truth | `lingtai-kernel-anatomy`, then cited code |

## System tool call contract

When operating the model-facing `system` family, use the exact LTP v2 envelope:

```json
{
  "action": "<one action from the installed schema>",
  "input": {"<fields for that action only>": "..."},
  "reasoning": "<short purpose>",
  "summarize": false
}
```

The root is closed: `action`, `input`, and `reasoning` are required, `summarize`
is the optional root result-control, and no other root keys are accepted. Each
action has its own closed `input`; do not move `address`, `preset`, `force`, or
`content` between branches. `system(action="summarize")` is not a supported
action: context hygiene belongs to `context(action="summarize")` and
`context(action="rebuild")`. The `sleep` input additionally carries the
required-nullable `delay` field for the last-resort one-shot alarm documented
in the substrate manual; pass `null` unless that exceptional route applies.

`presets` can return a large allowed-only catalog, so use the root
`summarize=true` only when exact entries are unnecessary. Refresh, sleep, lull,
suspend, cpr, interrupt, clear, nirvana, both name actions, and errors return
short receipts; leave `summarize=false` and read them exactly. The `manual`
action itself must always use `summarize=false`, otherwise the operating
procedure you requested may be summarized away before you can follow it.

### Cache-miss budget

System owns `<agent-workdir>/settings/system.json`; there is no per-action
settings file. The closed v1 document carries this one setting:

```json
{"schema_version": 1, "cache_miss_budget": 2000000}
```

Both values must be JSON integers (not booleans), the version must be `1`, the
budget must be positive, and no other or duplicate keys are accepted. Resolution
is live valid `LINGTAI_CACHE_MISS_BUDGET`, then live valid System JSON (the v1
budget, or the v2 `cache_miss_budget` field below), then the fixed `2,000,000`
default. Invalid env falls through; missing, unreadable, malformed, or invalid
JSON uses the default. A valid env bypasses the file. The reader never creates
or rewrites it.

Direct process-env and unshadowed file changes apply on the next metadata
snapshot; an `env_file` edit still needs refresh. Threshold changes and refreshes
do not reset cumulative `token_usage.session.cache_miss_tokens`; only molt does.
The threshold is advisory and never blocks a request. This path is unrelated to
`.notification/system.json`. Legacy `init.json`
`manifest.cache_miss_budget` is ignored and has no runtime effect.

### Runtime policy (v2)

The same file may instead be a closed v2 document carrying any subset of the
ordinary runtime-policy fields, for example:

```json
{"schema_version": 2, "context_limit": 200000, "max_rpm": 30, "streaming": true}
```

Accepted keys are exactly `context_limit` (positive integer or `null` = no
configured limit), `max_rpm` (integer `>= 0`; `0` disables gating), `streaming`
(boolean), `aed_timeout` (finite positive seconds), `max_aed_attempts` (integer
`>= 1`), `snapshot_interval` (finite positive seconds or `null` = off),
`activeness` (non-blank string or `null`), `cache_miss_budget` (positive
integer), and `notification_max_chars` (positive integer; Core still clamps it to
2048–10000 and `LINGTAI_NOTIFICATION_MAX_CHARS` still wins). Booleans never stand
in for numbers, `NaN`/`Infinity` are rejected, and an unknown, duplicate, or
invalid key rejects the whole document so nothing is applied partially. An
absent key and an explicit `null` are different: absent falls through to the
manifest, `null` is the configured value.

Each ordinary field resolves as valid `LINGTAI_CONTEXT_LIMIT` / `LINGTAI_MAX_RPM`
/ `LINGTAI_STREAMING` / `LINGTAI_AED_TIMEOUT` / `LINGTAI_MAX_AED_ATTEMPTS` /
`LINGTAI_SNAPSHOT_INTERVAL` (`off` disables) / `LINGTAI_ACTIVENESS` > valid v2
field > effective `init.json` manifest field > kernel default. The policy is
resolved once at CLI boot, before the first LLM service is built, and once on
every refresh, so the service, `AgentConfig`, and the session streaming flag
always agree; `init.json` and `system/manifest.resolved.json` are never
rewritten to reflect it. Enabling `snapshot_interval` by refresh on a running
agent initializes the snapshot repository first; if that fails, snapshots stay
off for the process and `snapshot_initialize_failed` is logged. The kernel-fixed
context-pressure thresholds (0.85 / 1.0 / 3 rounds / 0.75) and the legacy
`molt_*` fields are not settings: naming them makes the document invalid.

Use `presets` and the refresh pre-check route before any authorized preset swap
or refresh.

## How to choose between resident prompt, this router, and references

- If the resident prompt already answers the question, act.
- If the resident prompt names a broad system/runtime/procedure topic, read this
  router to choose the lower reference.
- If this router names a reference, read that reference before improvising.
- If a reference points to anatomy/code/tests, descend there for ground truth.

## Maintaining this router

`substrate` describes what an agent *is* and how the runtime behaves;
`procedures` describes how an agent *acts* — they stay separate on purpose.
Keep the resident prompt compact and keep this file a router: when resident
substrate/procedures gain new concepts, add a routing hint here and put the
detail in a nested reference. When a reference grows too large or needs
companion scripts and assets, split it into another `reference/<name>/SKILL.md`
folder and list it in both the nested reference catalog and the router table.
Keep this file short enough to scan.

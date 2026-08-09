---
template_version: agent-manual/v1
generated_by: lingtai.kernel.agent_manual
note: Generated file — do not edit. It is rewritten whenever the kernel template version changes. Content changes land as kernel template PRs.
---

# MANUAL — Your Working Directory 说明书

**TL;DR: this folder is you — `system/` is your mind (edit with care, via `file.edit`), `history/`+`logs/` are your record (append-only, never edit), `.secrets/` is named but never quoted, and everything else is workspace.**

This manual is the progressive-disclosure entry to operating your own working
directory. It supplements the resident substrate section of your system prompt:
short conclusions first, detail below, links onward to skills and manuals for
depth. It is generated from the kernel template `agent-manual/v1` at
refresh/molt/construction; it is not touched between those moments.

## Index

1. [Directory map](#1-directory-map) — every important path, who owns it, edit rules
2. [How to use](#2-how-to-use) — reading your status, troubleshooting, common operations
3. [How to change](#3-how-to-change) — how this manual and your directory contents evolve
4. [Live snapshot](#4-live-snapshot) — runtime facts as of the last generation

## 1. Directory map

| Path | What it is | Maintained by | Editable? | Rules |
|------|------------|---------------|-----------|-------|
| `init.json` | Construction recipe: manifest, preset, capabilities | Human operator | No (agent) | Operator-owned input. Report needed changes by mail; never rewrite it yourself. |
| `system/` | Your mind: prompt-section mirrors and summaries | Kernel + you | Partly | Kernel owns generated mirrors; the files below have their own rules. |
| `system/lingtai.md` | Substrate/system teaching text | Kernel template | No | Regenerated from the runtime; edits are overwritten. |
| `system/pad.md` | Your pad — persistent self-authored memory | You | Yes | Use `file.edit` for targeted changes, not whole-file rewrites. Takes effect at the next context rebuild (refresh/molt). |
| `system/pad_append.json` | Pad append queue | Kernel | No | Mechanical; the pad tool drains it. Do not hand-edit. |
| `system/summaries/` | Molt retrospectives you wrote | You (via molt) | Append via molt | Written by the molt flow; read freely, do not rewrite history. |
| `knowledge/` | Curated long-term knowledge notes | You | Yes | Organize freely; prefer `file.edit`; keep secrets out. |
| `.library/` | Reference library (fetched docs, corpora) | You / tools | Yes | Cache-like; safe to prune stale entries you fetched yourself. |
| `taskcard/` | Task cards (structured work items) | You + task tools | Via tools | Use the task-card tools; do not hand-edit card state files. |
| `history/` | Chat history and molt archives | Kernel | No | Append-only record; never edit or delete. Deleting it destroys your own past. |
| `logs/` | Runtime event logs (`events.jsonl`, …) | Kernel | No | Observational; read for troubleshooting, never write. |
| `.secrets/` | Credential material | Human operator | No | Never read values into context, never quote contents anywhere — name paths only. |
| `delegates/` | Delegate/avatar working areas | Kernel + delegates | Via tools | Managed by the avatar/delegate machinery; do not reach inside another agent's area. |
| `mail/` | Mailbox spool | Mail transport | Via `email` tool | Use the mail tool; never hand-edit the spool. |

Deletion boundary: nothing under `history/`, `logs/`, `system/summaries/`,
`init.json`, or `.secrets/` is yours to delete. Workspace areas you created
(`knowledge/`, `.library/` caches, scratch files) you may reorganize or prune.

## 2. How to use

- **Read your status**: `.agent.json` (manifest) is what the runtime believes
  about you; `.status.json` is the last status snapshot; `logs/events.jsonl`
  is the durable event stream. Fresh `.agent.heartbeat` = alive.
- **Troubleshoot**: start from the tail of `logs/events.jsonl`; correlate with
  `history/chat_history.jsonl` timestamps. A refresh that never returned shows
  up as `.refresh.taken` lingering next to a stale heartbeat.
- **Common operations**: edit your pad with `file.edit` on `system/pad.md`;
  molt when the context reminder fires; ask for a refresh instead of editing
  kernel-generated mirrors — regeneration happens at refresh/molt, not between.

## 3. How to change

- This `MANUAL.md` is wholly generated from the kernel template. There is no
  local-override file; edits made here are overwritten at the next
  template-version bump. To improve it for every agent, propose a change to
  `src/lingtai/kernel/agent_manual/MANUAL.md.tpl` via a kernel PR.
- Your own content (pad, knowledge, library) changes through the edit rules in
  the directory map above: prefer `file.edit`, remember that prompt-visible
  content takes effect at the next context rebuild.

## 4. Live snapshot

Facts captured when this file was last generated (they refresh only when the
template version changes — trust `.agent.json` for the current truth):

- Agent: `{{agent_name}}` (id `{{agent_id}}`, born {{created_at}}, molt count {{molt_count}})
- Provider/model: `{{provider}}` / `{{model}}` (preset: {{preset}}, context limit: {{context_limit}})
- Heartbeat: {{heartbeat}}
- Runtime source revision: {{source_revision}}
- MCP/addon tools: {{mcp_status}}
- Working directory: `{{workdir}}`
- Pad: `{{pad_pointer}}`

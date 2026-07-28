---
name: substrate-manual
description: >
  Routing table for the `substrate` tool — the one public root for your four
  durable domains (pad, 灵台, knowledge, skills). Read this to learn which action
  loads which manual, and the one mutation/rebuild model all four share.
related_files:
- src/lingtai/tools/substrate/CONTRACT.md
- src/lingtai/tools/substrate/ANATOMY.md
- src/lingtai/intrinsic_skills/pad-manual/SKILL.md
- src/lingtai/intrinsic_skills/lingtai-manual/SKILL.md
- src/lingtai/tools/knowledge/manual/SKILL.md
- src/lingtai/tools/skills/manual/SKILL.md
- src/lingtai/intrinsic_skills/context-manual/SKILL.md
maintenance: |
  This is the substrate family's own manual, loaded by
  `substrate(action='manual', input={}, reasoning='...')`.
  It is a routing table by design: keep it short and keep the depth in the four
  domain manuals it points to. Update it together with
  src/lingtai/tools/substrate/{CONTRACT,ANATOMY}.md whenever the public action
  inventory, a domain's durable source, or the rebuild model changes.
---

# Substrate

Your **substrate** is what survives a molt: the four durable domains that are
re-read and recomposed into every fresh system prompt. `substrate` is the one
public root that teaches them. It is a signpost family — every action returns a
manual and changes nothing.

## Routing table

| Call | Returns | Durable source it teaches |
|---|---|---|
| `substrate(action="pad", input={}, reasoning="load Pad guidance")` | `pad-manual` | `system/pad.md` + pinned references in `system/pad_append.json` |
| `substrate(action="lingtai", input={}, reasoning="load identity guidance")` | `lingtai-manual` | `system/lingtai.md` (your 灵台 / character) |
| `substrate(action="knowledge", input={}, reasoning="load knowledge guidance")` | the knowledge manual | `knowledge/<name>/KNOWLEDGE.md` entries |
| `substrate(action="skills", input={}, reasoning="load skills guidance")` | the skills manual | `.library/{intrinsic,custom}/` plus configured skills paths |
| `substrate(action="manual", input={}, reasoning="load the routing table")` | this routing table | — |

Every action takes a strict empty `input`, and root `reasoning` is required on
every call. Any key inside `input` is rejected before the manual is even read, so
there is nothing to pass and nothing to smuggle.

## The one mutation model

`substrate` has **no** mutating action. That is deliberate, not an omission:
durable content is ordinary text, so it is changed by the ordinary text tools.

1. **Write** the durable source with `file.write` (create or full overwrite) or
   `file.edit` (exact replacement).
2. **Apply** it with one explicit
   `context(action="rebuild", input={}, reasoning="apply durable changes")`.

File mutation never hot-loads the prompt. A durable change you have written but
not rebuilt is real on disk and simply not yet visible in your context — that
separation is what makes a batch of edits land atomically instead of one
half-composed section at a time.

A full rebuild re-reads and recomposes **all** enabled canonical sections once,
applies pending summaries, and then requests provider replay. Passive
reconstruction — `system(action="refresh", ...)` and molt — runs that same contract,
so the four domains are preserved identically whichever path you take. You do
not need a per-domain reload, and there is no per-domain reload to call.

Catalog upkeep is not yours to trigger either. Skills and Knowledge catalogs are
rescanned and recomposed by that same reconstruction path (and at setup/refresh);
authoring a new `KNOWLEDGE.md` or `SKILL.md` and then rebuilding is the whole
procedure.

## Which domain am I in?

- Working notes, the current task, the living index you tend every turn → **pad**.
- Who you are, your voice, how you carry yourself → **lingtai** (灵台).
- Something you learned, decided, or discovered and want back after a molt,
  possibly referencing local paths, mail ids, or logs → **knowledge**.
- A reusable procedure that would help any agent, not just you → **skills**.

When the choice is genuinely unclear, read the two candidate manuals before
writing; the domain manuals own that distinction in depth and this table does not
restate it.

## `summarize`

**Short-result.** Every substrate action returns one manual body. `summarize` is
available at root but normally unnecessary here, and a summarized manual loses
the exact procedure and constraints you called it for — leave it `false`.

## Settings

`substrate` owns no settings file at either level: there is no
`settings/substrate.json` and no `settings/substrate.<action>.json`. Nothing to
configure, and an unrecognized file there is not read by this family.

---
name: pad-manual
description: |
  Operational guide for the pad tool — the sketchboard in your system prompt (system/pad.md). Read this when: you are deciding what belongs in your pad; you want the tending rhythm; you need to pin reference files with pad(action='append'); or you are archiving a completed pad. Pad is a store you tend before molting — the molt procedure itself lives in context-manual.
version: 1.0.0
last_changed_at: 2026-07-27T18:00:00-07:00
related_files:
- src/lingtai/tools/pad/__init__.py
- src/lingtai/tools/pad/_pad.py
- src/lingtai/tools/pad/CONTRACT.md
- src/lingtai/intrinsic_skills/context-manual/SKILL.md
maintenance: |
  Tracks the pad tool's behavior; update when that tool's actions, inputs, limits, or persistence paths change. Pad is one of the four durable stores tended before a molt — keep the routing line to context-manual (molt procedure) and to lingtai-manual (identity) accurate rather than restating either.
---

# Pad Manual

Pad is your **living index** of what you are working on right now. It is not a
sketchpad or a scratchpad. Treat it as your personal table of contents, held in
`system/pad.md` and rendered into your system prompt on every load.

## Call shape

```
pad(action="edit",   input={"content": <full pad body>, "files": null}, reasoning="why")
pad(action="load",   input={}, reasoning="why")
pad(action="append", input={"files": ["path/one.md", "path/two.py"]}, reasoning="why")
pad(action="manual", input={}, reasoning="why")
```

One `action`, that action's own strict `input` object, and a root `reasoning`.
Leave the root `summarize` false: pad results are small (short-result profile),
and summarizing a `manual` call would drop the exact procedure you called it
for.

`pad` is its own tool. It used to be reachable as `psyche(action="pad_edit")`
and friends; that spelling is gone with no alias and now fails as an unknown
psyche action.

## Purpose: progressive disclosure for your future self

Pad is shallow and direct; the things it points at are deep and structured. A
glance at pad tells the next you the *shape* of what is going on.

**What belongs in pad:**

- **The active goal** — what you are working on, in your own words.
- **Where you are in it** — the next concrete step, the current blocker.
- **Timestamps** — always include when each entry was last updated. Without
  them, you cannot distinguish old information from new.
- **Pointers to where the substance lives:**
  - knowledge entry paths (`knowledge/<name>/KNOWLEDGE.md`)
  - skills SKILL.md paths (`.library/custom/<name>/SKILL.md`)
  - email message IDs of load-bearing conversations
  - file paths under your workdir that matter
  - URLs you are tracking
- **Collaborators** — who you are working with, who is waiting on what.

**What does NOT belong in pad:** large blobs of inlined text, full file
contents, transcripts. If you find yourself pasting a long passage, stop —
write it as knowledge and *point at* the path instead. Pad indexes the depths;
it does not become them.

## Tending rhythm

**When to update pad:** whenever the index meaningfully changes — a new
reference, a goal shift, a step change. Do not churn on every step, but do not
hoard updates for the end either. A stale pad is worse than a noisy pad.

This rhythm is deliberately different from `lingtai` and `knowledge`, which are
tended *once* per task at the end (see `lingtai-manual`).

## `edit` is a full rewrite

`pad(action="edit", ...)` REPLACES the whole pad body — it is not an append.
Include everything you want to keep. Passing `content=""` clears the pad
explicitly. Passing neither `content` nor `files` is refused rather than
silently clearing it.

The optional `files` list imports those files' contents into the pad body as
`[file-N]` blocks *at edit time* — a one-time snapshot, distinct from the
re-read pinning `append` does.

## `append` for file pinning

`pad(action="append", input={"files": [...]}, reasoning="...")` pins file
contents as read-only reference in your system prompt — they are re-read and
appended on every load, **including after molt**. Pin anything you want
persistent visibility on: source files, skill docs, configs.

- Pass `files=[]` to clear the pin list.
- Pass `files=null` to read the current list without changing it.
- Total appended content must not exceed 100k tokens.
- Paths are relative to your working directory; only text files are accepted.

## Archiving completed pads

When a goal completes, archive to `archive/pad-<goal-slug>-<YYYY-MM-DD>.md`.
Then `pad(action="edit", input={"content": <next goal>, "files": null},
reasoning="...")`. Remember that `edit` is a FULL REWRITE of the pad, not an
append.

## Relationship to molt

Pad is one of the four durable stores. It survives a molt and is reloaded into
the fresh session's system prompt automatically — which is exactly why it must
be accurate *before* you molt. The molt procedure, the store-tending checklist,
and the session-journal gate all live in `context-manual`; read it there rather
than improvising from here.

## Settings

Pad supports no settings file at either level — there is no
`settings/pad.json` and no `settings/pad.<action>.json`. Its persistence is
`system/pad.md` (the body) and `system/pad_append.json` (the pin list), both
managed by the tool itself.

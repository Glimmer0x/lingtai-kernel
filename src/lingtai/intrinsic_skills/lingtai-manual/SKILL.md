---
name: lingtai-manual
description: |
  Operational guide for the lingtai tool — your 灵台 (character), the self-authored identity that distinguishes you from every other agent. Read this when: you are updating your identity; you need the tending rhythm; or you need to understand the two identity modes (self-evolve vs forced) and how configured values interact with your own writes. Identity is a store you tend before molting — the molt procedure itself lives in psyche-manual.
version: 1.0.0
last_changed_at: 2026-07-27T18:00:00-07:00
related_files:
- src/lingtai/tools/lingtai/__init__.py
- src/lingtai/tools/lingtai/_lingtai.py
- src/lingtai/tools/lingtai/CONTRACT.md
- src/lingtai/intrinsic_skills/psyche-manual/SKILL.md
maintenance: |
  Tracks the lingtai tool's behavior; update when that tool's actions, inputs, identity modes, or persistence paths change. Identity is one of the four durable stores tended before a molt — keep the routing line to psyche-manual (molt procedure) and to pad-manual (working index) accurate rather than restating either.
---

# LingTai Manual

Your 灵台 is what distinguishes you from every other agent — the self-authored
identity held in `system/lingtai.md` and rendered into the protected
`character` section of your system prompt.

## Call shape

```
lingtai(action="update", input={"content": <your full identity>}, reasoning="why")
lingtai(action="load",   input={}, reasoning="why")
lingtai(action="manual", input={}, reasoning="why")
```

One `action`, that action's own strict `input` object, and a root `reasoning`.
Leave the root `summarize` false: lingtai results are small (short-result
profile), and summarizing a `manual` call would drop the exact procedure you
called it for.

`lingtai` is its own tool. It used to be reachable as
`psyche(action="lingtai_update")` / `psyche(action="lingtai_load")`; that
spelling is gone with no alias and now fails as an unknown psyche action.

## `update` is a full rewrite

`lingtai(action="update", ...)` REPLACES `system/lingtai.md` entirely — it is
not a delta. Carry forward who you have become; include your whole identity,
not just what changed. Passing `content=""` clears it. The write auto-loads
immediately, so the new `character` section is live in the same cycle.

## Tending rhythm

Identity tending happens **once per task, at the end** — not mid-task. Hold
updates in your head while working, then commit them in a single pass before
going idle (or before molting). Mid-task edits create noise and waste tokens.
The exception is a long-running task where a crash would genuinely destroy
work — checkpoint deliberately in that case.

This is the same rhythm `knowledge` follows, and deliberately different from
`pad`, which is updated whenever the index meaningfully changes (see
`pad-manual`).

## Identity modes

`lingtai` supports two intentional modes.

**Self-evolve mode (recommended)** omits the configured identity, or sets it
empty. Boot, refresh, and post-molt reconstruction leave `system/lingtai.md`
untouched, so identity changes you author persist across every reconstruction.

**Forced identity mode** uses a nonempty resolved `lingtai` value in the init
configuration, either inline or from `lingtai_file`. That value is
authoritative and is materialized into `system/lingtai.md` on each
reconstruction. A `lingtai(action="update")` still writes and auto-loads
immediately in the current cycle, but the configured forced value replaces it
at the next reconstruction.

Keep your 灵台 distinct from three neighbouring sections you do not own:

- the operator `covenant` (`system/covenant.md`),
- the third-party `base_prompt`,
- the mechanical `identity` section (name/nickname/manifest, written by the
  kernel).

`lingtai(action="load")` is the single canonical writer of the `character`
section, composed from `system/lingtai.md` alone. An empty or missing file
deletes the section.

## Relationship to molt

Your 灵台 is one of the four durable stores. It survives a molt and is reloaded
into the fresh session's system prompt automatically — which is exactly why it
must be current *before* you molt: the next you wakes with the identity you
last wrote, not with the conversation you had. The molt procedure, the
store-tending checklist, and the session-journal gate live in `psyche-manual`;
read it there rather than improvising from here.

## Settings

LingTai supports no settings file at either level — there is no
`settings/lingtai.json` and no `settings/lingtai.<action>.json`. Its
persistence is `system/lingtai.md`, managed by the tool itself; the
configured-identity value described under "Identity modes" comes from the agent
manifest, not from an LTP settings file.

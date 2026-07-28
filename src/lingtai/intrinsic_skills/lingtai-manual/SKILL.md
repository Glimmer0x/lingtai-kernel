---
name: lingtai-manual
description: |
  Signpost and operational guide for the agent's 灵台 identity in system/lingtai.md. Read this before changing identity, choosing forced versus self-evolve behavior, or applying durable identity changes to context.
version: 2.0.0
last_changed_at: 2026-07-28T00:00:00-07:00
related_files:
- src/lingtai/tools/lingtai/__init__.py
- src/lingtai/tools/lingtai/_lingtai.py
- src/lingtai/tools/lingtai/CONTRACT.md
- src/lingtai/intrinsic_skills/context-manual/SKILL.md
maintenance: |
  Keep the manual-only public root, generic file ownership, no-hot-load rule, identity modes, and context reconstruction route synchronized with code.
---

# LingTai Manual

Your 灵台 is the character that distinguishes you from every other agent. Its
durable source is `system/lingtai.md`; canonical reconstruction renders it into
the protected `character` system-prompt section.

## Public call

```text
lingtai(action="manual", input={}, reasoning="load identity guidance", summarize=false)
```

`manual` is the **only** public LingTai action. It is a signpost, like the
skills/knowledge manuals, and performs no disk or prompt mutation. There is no
public update/load action and no compatibility alias.

## Change durable identity with file

- Full rewrite: `file(action="write", input={"file_path":
  "system/lingtai.md", "content": <your complete identity>}, reasoning="...")`.
- Exact replacement: `file(action="edit", input={"file_path":
  "system/lingtai.md", "old_string": <exact>, "new_string": <replacement>,
  "replace_all": null}, reasoning="...")`.

A full rewrite must carry forward everything you intend to keep. An exact edit
is appropriate for a bounded, unambiguous change. Neither operation hot-loads
or otherwise mutates the current prompt.

To apply the durable change now, call one explicit
`context(action="rebuild", input={}, reasoning="apply durable identity")`.
Otherwise it takes effect on passive refresh/molt reconstruction.

## Identity modes

- **Self-evolve:** configured `lingtai`/`lingtai_file` is absent or empty.
  Reconstruction preserves and composes your self-authored
  `system/lingtai.md`.
- **Forced:** configuration resolves to a nonempty identity. Every
  reconstruction materializes that configured value into `system/lingtai.md`
  before composing it, so a file change is replaced at the next rebuild,
  refresh, or molt.

Keep character separate from operator `covenant`, third-party `base_prompt`,
and mechanical name/manifest `identity`. Names remain
`system(action="name_set"|"name_nickname")`.

Before molt, tend identity once when the task's lessons genuinely changed who
you are; use `context-manual` for the journal/summary/molt procedure. LingTai has
no settings file. Manual results are short; leave root `summarize` false.

---
name: pad-manual
description: |
  Operational guide for Pad's pinned read-only reference list and for editing the durable Pad body through file. Read this before pinning references, changing system/pad.md, or preparing Pad state for rebuild/molt.
version: 2.0.0
last_changed_at: 2026-07-28T00:00:00-07:00
related_files:
- src/lingtai/tools/pad/__init__.py
- src/lingtai/tools/pad/_pad.py
- src/lingtai/tools/pad/CONTRACT.md
- src/lingtai/intrinsic_skills/context-manual/SKILL.md
maintenance: |
  Keep the append-only public surface, no-hot-load rule, file ownership, delayed activation, limits, and context-manual route synchronized with code.
---

# Pad Manual

Pad is your living index in `system/pad.md`, plus a durable list of pinned
read-only references in `system/pad_append.json`.

## Public calls

```text
pad(action="append", input={"files": ["path/one.md", "path/two.py"]}, reasoning="pin references")
pad(action="append", input={"files": []}, reasoning="clear references")
pad(action="append", input={"files": null}, reasoning="inspect references")
pad(action="manual", input={}, reasoning="load Pad guidance", summarize=false)
```

The exact public actions are `append | manual`. There is no Pad body edit or
load action and no compatibility alias.

## Mutate durable Pad content with file

- Full create/overwrite: `file(action="write", input={"file_path":
  "system/pad.md", "content": <complete body>}, reasoning="...")`.
- Exact replacement: `file(action="edit", input={"file_path":
  "system/pad.md", "old_string": <exact>, "new_string": <replacement>,
  "replace_all": null}, reasoning="...")`.

`file.write` is a full-file operation; include everything you intend to keep.
`file.edit` replaces exact text and fails if the target is missing/ambiguous.

**Neither file operation reloads or mutates the current prompt.** After durable
changes, call one explicit `context(action="rebuild", input={}, reasoning="apply
durable prompt changes")`, or let passive refresh/molt reconstruction apply
them later.

## Pin references

`pad.append` validates every supplied path as existing UTF-8 text and enforces a
100,000-token aggregate limit before persisting the list. `[]` clears; null only
queries. Paths may be workdir-relative or absolute.

**Append also never hot-loads the prompt.** Its result says
`prompt_reload: false` and names when it takes effect. Use `context.rebuild`
when the new list must become visible now. The reconstruction path re-reads each
pinned file, so later file changes also appear only after reconstruction.

Keep Pad concise: current goal, state, next action, blockers, collaborators, and
pointers to substantive knowledge/artifacts. Archive completed narrative in
knowledge, not in an ever-growing Pad. Before molt, make durable Pad state
accurate, rebuild only if needed in the current context, then follow
`context-manual` for the journal/summary/molt procedure.

Pad has no settings file. Results are short; leave root `summarize` false.

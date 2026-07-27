---
related_files:
  - src/lingtai/ANATOMY.md
  - src/lingtai/agent.py
  - src/lingtai/tools/daemon/__init__.py
  - src/lingtai/tools/skills/__init__.py
  - src/lingtai/tools/skills/manual/SKILL.md
  - src/lingtai/init_schema.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/skills/CONTRACT.md
  - tests/test_skills.py
  - tests/test_validate_skill.py
  - src/lingtai/tools/skills/glossary-en.md
  - src/lingtai/tools/skills/glossary-zh.md
  - src/lingtai/tools/skills/glossary-wen.md
maintenance: |
  Keep related_files as repo-relative paths to real files. Include neighboring
  ANATOMY.md files so the anatomy graph stays connected rather than isolated;
  anatomy links must be bidirectional. If you create a new ANATOMY.md, copy this
  maintenance field. If you notice drift between this anatomy and the code,
  report it. See lingtai-dev-guide for details.
---
# core/skills

Skills capability — per-agent skill catalog and skill-manual surface. This is the renamed successor of the old `library` capability. It scans the existing `.library/` directory plus configured extra paths, renders a YAML catalog (one `- name:` block per skill with `location:` and a `description:` block scalar), and injects it into the `skills` prompt section. It never writes skill files; installation remains the Agent initializer's job.

## Components

- `skills/__init__.py` — the capability implementation. The canonical strict-empty child input factory `_strict_empty_input` (`__init__.py:54-55`), `_reconcile` (`__init__.py:87-171`), `_skills_info` (`__init__.py:174-179`), the Host-owned `_adapt_manual_result` flattener (`__init__.py:182-204`), `get_description` (`__init__.py:207-208`), the single canonical child-registry builder `_build_family` and its import-time schema-only instance `_SCHEMA_FAMILY` (`__init__.py:211-246`), `get_schema` (`__init__.py:249-252`), `setup` with its `handle_skills` wrapper (`__init__.py:255-292`), and path/scanner helpers (`__init__.py:62-80`).
- `skills/manual/` — `skills-manual` skill documentation, template assets, and validator script. The validator can optionally require `last_changed_at` for LingTai-maintained skill bundles.

## Connections

- `lingtai.tools.registry` maps canonical `skills` here. Former skill-catalog `library.paths` compatibility is removed in the clean rename.
- `Agent._install_intrinsic_manuals()` copies every capability `manual/` bundle into `.library/intrinsic/capabilities/<name>/`, then re-runs `skills._reconcile()` for first-turn catalog freshness when `skills` is loaded (`src/lingtai/agent.py:256`).
- The daemon capability blacklists `skills` so emanations do not recursively receive the skill catalog tool (`../daemon/__init__.py:34`).
- The generic [`../tool_family/ANATOMY.md`](../tool_family/ANATOMY.md) owns the reusable schema-composition/dispatch infrastructure this package builds its `ToolFamily` instances from, and the reserved `manual` child builder (`tool_family/manual.py`). It has no knowledge of the skill catalogue.
- `lingtai.kernel.tool_result_summary` lists `skills` in `_LTP_V2_MIGRATED_FAMILIES`, so this family's root `summarize` boolean is recognized as the canonical a-priori summary control (`src/lingtai/kernel/tool_result_summary.py:155`).

## Public API

`skills` is a migrated LTP v2 family: one model-facing root, closed to exactly
`action`, `input`, `reasoning`, and `summarize`, with `required: [action,
input, reasoning]`. The public tool name and both public action values are
unchanged by the migration; each action value equals its child/dispatch key.
Both children take the canonical strict-empty `input` object.

| Action | Input | Description |
|---|---|---|
| `info` | `{}` (strict-empty) | Refresh/reconcile the skills catalog and return runtime health (catalog size, paths report, problems) without manual bodies |
| `manual` | `{}` (strict-empty) | Return the skills manual body plus the library manual body on demand, without any catalogue mutation |

`handle_skills` delegates envelope validation and dispatch to the agent-bound
`ToolFamily`, then flattens only the reserved `manual` child's canonical
`content`/`structuredContent` result back to this capability's public
`skills_manual`/`library_manual`/`manual_path` shape — strictly after dispatch,
never inside a registered child, and never wrapping either child's result.

## State

- Skill storage remains `<agent>/.library/` for compatibility: `intrinsic/` is CLI-managed and `custom/` is agent-authored (`__init__.py:112-115`).
- Config path source is canonical `manifest.capabilities.skills.paths` (`src/lingtai/init_schema.py:403-421`).
- Prompt state is the `skills` section, written only by `_reconcile` — reached by `setup` and the `info` child, never by `manual` (`__init__.py:150-155`).
- Health check expects `.library/intrinsic/capabilities/skills/SKILL.md` and reports `skills_manual`, with `library_manual` retained as a response compatibility key (`__init__.py:157-183`).

## Notes

- The `.library/` directory name and `.library_shared/` convention are intentionally preserved in this rename-only change; they are storage compatibility names, not the user-facing capability name.
- New callers should use `skills({"action":"info","input":{},"reasoning":"..."})`; old `library({"action":"info"})` is not registered because private durable memory is now `knowledge` and `library` is not registered.
- LingTai-maintained `SKILL.md` files carry `last_changed_at` in frontmatter, initialized from git history for metadata-only backfills and updated on substantive skill edits.

---
related_files:
  - src/lingtai/ANATOMY.md
  - src/lingtai/agent.py
  - src/lingtai/tools/daemon/__init__.py
  - src/lingtai/tools/skills/BEHAVIORS.md
  - src/lingtai/tools/skills/__init__.py
  - src/lingtai/tools/skills/manual/SKILL.md
  - src/lingtai/init_schema.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/skills/CONTRACT.md
  - src/lingtai/tools/psyche/ANATOMY.md
  - tests/test_skills.py
  - tests/test_validate_skill.py
  - src/lingtai/tools/skills/glossary-en.md
  - src/lingtai/tools/skills/glossary-zh.md
  - src/lingtai/tools/skills/glossary-wen.md
  - src/lingtai/tools/skills/manual/assets/skill-template.md
  - src/lingtai/tools/skills/manual/reference/cleanup-footprint-contract.md
  - src/lingtai/tools/skills/manual/scripts/validate.py
maintenance: |
  Keep related_files as repo-relative paths to real files. Include neighboring
  ANATOMY.md files so the anatomy graph stays connected rather than isolated;
  anatomy links must be bidirectional. If you create a new ANATOMY.md, copy this
  maintenance field. If you notice drift between this anatomy and the code,
  report it. See lingtai-dev-guide for details.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# core/skills

Skills capability — per-agent skill catalog and skill-manual surface. This is the renamed successor of the old `library` capability. It scans the existing `.library/` directory plus configured extra paths, renders a YAML catalog (one `- name:` block per skill with `location:` and a `description:` block scalar), and injects it into the `skills` prompt section. It never writes skill files; installation remains the Agent initializer's job.

## Components

- `skills/__init__.py` — the capability implementation. It registers **no** model-facing tool: the former public `skills` root and its `info` action were retired into the read-only `psyche(action='skills')` manual loader. Path helpers `_resolve_path` (`__init__.py:58-72`) and `_scan` (`__init__.py:75-76`), the catalog composer `_reconcile` (`__init__.py:83-171`), and the capability lifecycle entry `setup` (`__init__.py:178-196`).
- `skills/manual/` — `skills-manual` skill documentation, template assets, and validator script. The validator can optionally require `last_changed_at` for LingTai-maintained skill bundles. This is the body `psyche(action='skills')` returns.

## Connections

- `lingtai.tools.registry` maps canonical `skills` here as a *capability* (`BUILTIN_TOOLS`/`CORE_DEFAULTS`); it is not an intrinsic and registers no tool. Former skill-catalog `library.paths` compatibility is removed in the clean rename.
- `Agent._install_intrinsic_manuals()` copies every capability `manual/` bundle into `.library/intrinsic/capabilities/<name>/`, then re-runs `skills._reconcile()` for first-turn catalog freshness when `skills` is loaded (`src/lingtai/agent.py:490-501`).
- `Agent._reload_prompt_sections` re-runs `_reconcile(..., publish=False)` so a full `context.rebuild` (and passive refresh/molt reconstruction) recomposes this catalog with every other canonical section before one final prompt publication (`src/lingtai/agent.py:1821-1848`).
- [`../psyche/ANATOMY.md`](../psyche/ANATOMY.md) owns the one public root; it loads this package's `manual/SKILL.md` and holds no reference to the catalog or its composer.
- The daemon capability blacklists `skills` so emanations do not borrow it from the host tool floor (`../daemon/__init__.py:435`).
- The generic [`../tool_family/ANATOMY.md`](../tool_family/ANATOMY.md) owns the reusable schema-composition/dispatch infrastructure. This package no longer builds a `ToolFamily`; only `psyche` does.

## Public API

None. This package exposes no model-facing tool, schema, or dispatch entry
point. Its public surface is the read-only `psyche(action='skills')` manual
loader, owned by [`../psyche/CONTRACT.md`](../psyche/CONTRACT.md).

`setup(agent, paths=...)` is the capability lifecycle entry point: it reconciles
the catalog and injects the `skills` prompt section. `_reconcile` is the private
composer shared by that setup/refresh path and by full-context reconstruction.

## State

- Skill storage remains `<agent>/.library/` for compatibility: `intrinsic/` is CLI-managed and `custom/` is agent-authored (`__init__.py:95-98`).
- Config path source is canonical `manifest.capabilities.skills.paths` (`src/lingtai/init_schema.py:442-446`).
- Prompt state is the `skills` section, written only by `_reconcile` — reached by `setup` and by full-context reconstruction, never by a model-facing action (`__init__.py:133-142`).
- Health check expects `.library/intrinsic/capabilities/skills/SKILL.md` and reports `skills_manual`, with `library_manual` retained as a response compatibility key (`__init__.py:145-167`).

## Notes

- The `.library/` directory name and `.library_shared/` convention are intentionally preserved in this rename-only change; they are storage compatibility names, not the user-facing capability name.
- There is no `skills` tool call any more: use `psyche(action="skills", input={}, reasoning="load the Skills manual")` for the manual, and let setup/refresh or `context.rebuild` reconcile the catalog. The retired `library` root is likewise not registered.
- LingTai-maintained `SKILL.md` files carry `last_changed_at` in frontmatter, initialized from git history for metadata-only backfills and updated on substantive skill edits.

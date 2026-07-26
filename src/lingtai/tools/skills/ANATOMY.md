---
related_files:
  - src/lingtai/ANATOMY.md
  - src/lingtai/agent.py
  - src/lingtai/tools/daemon/__init__.py
  - src/lingtai/tools/skills/__init__.py
  - src/lingtai/tools/skills/CONTRACT.md
  - src/lingtai/tools/skills/manual/SKILL.md
  - src/lingtai/init_schema.py
  - src/lingtai/tools/_settings.py
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

Skills capability — per-agent skill catalog and skill-manual surface. This is the
renamed successor of the old `library` capability. It scans the existing
`.library/` directory plus configured extra paths, renders a YAML catalog (one
`- name:` block per skill with `location:` and a `description:` block scalar), and
injects it into the `skills` prompt section. It never writes skill files;
installation remains the Agent initializer's job.

## Components

- `skills/__init__.py` — capability implementation. `_resolve_path`
  (`__init__.py:52-62`) handles absolute, relative, and tilde paths; `_scan`
  (`__init__.py:69-70`) delegates Markdown catalog parsing; `_reconcile`
  (`__init__.py:77-161`) scans `.library/` and Tier-1 paths, injects the protected
  catalog, and reports health while preserving all compatibility response keys.
- `get_description` (`__init__.py:196-205`) documents the two nested calls with
  root `action`, empty `input`, and Agent-injected `reasoning`; `get_schema`
  (`__init__.py:208-241`) is the closed raw schema with required `action` +
  `input.anyOf` branches titled `info input` and `manual input`.
- `setup` (`__init__.py:244-322`) preserves setup-time reconciliation and the
  initializer boundary, then registers `handle_skills` with catalog path
  injection unchanged. The handler (`__init__.py:263-314`) rereads foundation
  settings before every invocation, accepts root `action`, `input`, canonical
  `reasoning`, and executor `_reasoning`, validates an empty mapping input,
  dispatches only `action` and `input` without flat compatibility, and attaches
  `current_setting` to every outcome.
- `skills/manual/` — `skills-manual` skill documentation, template assets, and
  validator script. The validator can optionally require `last_changed_at` for
  LingTai-maintained skill bundles.

## Connections

- `lingtai.tools.registry` maps canonical `skills` here. Former skill-catalog
  `library.paths` compatibility is removed in the clean rename.
- `Agent._install_intrinsic_manuals()` copies every capability `manual/` bundle into
  `.library/intrinsic/capabilities/<name>/`, then re-runs `skills._reconcile()` for
  first-turn catalog freshness when `skills` is loaded (`src/lingtai/agent.py:256`).
- The daemon capability blacklists `skills` so emanations do not recursively
  receive the skill catalog tool (`../daemon/__init__.py:34`).
- The handler reads the shared no-op settings foundation
  (`src/lingtai/tools/_settings.py:108-156`) but settings never select or alter
  skills behavior; the `settings/skills.json` evidence is surfaced as
  `current_setting` only.

## Public API

The `skills` tool exposes two signpost actions using a required nested empty
input. The raw module schema has only `action` and `input`; it has no metadata
properties. After registration, `BaseAgent` adds optional root `reasoning` to
form the final Agent/model-facing schema, and `ToolExecutor` may pass that
metadata internally as `_reasoning`. The direct handler accepts either root
metadata spelling, and neither belongs inside `input` or reaches dispatch.

| Action | Description |
|---|---|
| `info` | `skills(action="info", input={}, reasoning="refresh the catalog")` refreshes/reconciles the skills catalog and returns runtime health (catalog size, paths report, problems) without manual bodies |
| `manual` | `skills(action="manual", input={}, reasoning="read skills guidance")` returns the installed skills manual body plus `library_manual` on demand |

Direct action-only, flat, non-object, or non-empty-input calls are malformed
errors. Unknown actions retain the historical exact message text, but not the entire
response envelope because `current_setting` is now attached. All success, degraded,
malformed, and unknown results include the truthful per-call `current_setting` value.

## State

- Skill storage remains `<agent>/.library/` for compatibility: `intrinsic/` is
  CLI-managed and `custom/` is agent-authored (`__init__.py:89-92`).
- Config path source is canonical `manifest.capabilities.skills.paths`
  (`src/lingtai/init_schema.py:403-421`).
- Prompt state is the protected `skills` section (`__init__.py:127-133`).
- Health check expects `.library/intrinsic/capabilities/skills/SKILL.md` and reports
  `skills_manual`, with `library_manual` retained as a response compatibility key
  (`__init__.py:135-160`).
- The settings placeholder is Agent-owned at `settings/skills.json`; the reader
  rereads it on every handler invocation and reports missing/valid/invalid states
  without changing scanner, path resolution, reconciliation, catalog injection,
  or manual behavior.

## Notes

- The `.library/` directory name and `.library_shared/` convention are intentionally
  preserved in this rename-only change; they are storage compatibility names, not
  the user-facing capability name.
- New callers should use `skills(action="info", input={}, reasoning="refresh the catalog")`;
  old `library({"action":"info"})` is not registered because private durable memory
  is now `knowledge` and `library` is not registered.
- LingTai-maintained `SKILL.md` files carry `last_changed_at` in frontmatter,
  initialized from git history for metadata-only backfills and updated on
  substantive skill edits.

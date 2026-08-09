---
related_files:
  - src/lingtai/kernel/agent_manual/CONTRACT.md
  - src/lingtai/kernel/ANATOMY.md
  - src/lingtai/kernel/agent_manual/__init__.py
  - src/lingtai/kernel/agent_manual/MANUAL.md.tpl
  - src/lingtai/kernel/workdir.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/tools/context/_molt.py
  - tests/test_agent_manual.py
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  Keep this component's ANATOMY.md and CONTRACT.md reciprocal and keep
  parent/child anatomy links bidirectional. Code is the structural source of
  truth: update this anatomy in the same change that moves files, symbols,
  connections, composition, or state. Verify every changed citation and run the
  architecture-document validation before merge.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
---
# Agent Manual Anatomy

The agent-manual package generates each agent working directory's root
`MANUAL.md` — the agent's own operational guide (说明书) — from a kernel-owned
template, on a mechanical template-version check.

## Components

- `MANUAL.md.tpl` — the authoritative template: a `template_version` head
  (`agent-manual/v1`), static teaching sections (directory map, how to use,
  how to change), and `{{key}}` placeholders for the live-snapshot section
  (`src/lingtai/kernel/agent_manual/MANUAL.md.tpl`).
- `render_manual(facts, template=None)` — pure renderer: scrubs secret-named
  keys from the facts dict, substitutes placeholders, returns text
  (`src/lingtai/kernel/agent_manual/__init__.py`).
- `ensure_agent_manual(layout_or_root, *, facts=None)` — the idempotent write
  path: compares the existing file's head `template_version` with the packaged
  template's and rewrites atomically only when missing or stale
  (`src/lingtai/kernel/agent_manual/__init__.py`).
- `collect_agent_facts(agent, manifest=None)` — fail-soft facts gathering
  from a (Base)Agent for the live-snapshot section
  (`src/lingtai/kernel/agent_manual/__init__.py`).
- `WorkdirLayout.manual` names the `<root>/MANUAL.md` path
  (`src/lingtai/kernel/workdir.py`).

## Connections

Three fail-soft mounts call `ensure_agent_manual`, one per context-rebuild
moment: `_perform_refresh` (`src/lingtai/kernel/base_agent/lifecycle.py`),
agent molt (`src/lingtai/tools/context/_molt.py`), and `BaseAgent`
construction — the path avatars reach
(`src/lingtai/kernel/base_agent/__init__.py`). The renderer reads the template
via `importlib.resources`, writes through `_fsutil.atomic_write_text`, and
reuses `workdir._redact_secrets` for the secret-key scrub. Packaging ships the
template and this document pair via the `lingtai.kernel.agent_manual`
package-data entry (`pyproject.toml`).

## State

One generated artifact: `<working_dir>/MANUAL.md`. Its head `template_version`
is the only regeneration trigger; no timestamps, counters, or per-heartbeat
state. Behavior is pinned by `tests/test_agent_manual.py`; the normative
boundary is the paired `CONTRACT.md`.

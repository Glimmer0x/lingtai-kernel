---
name: agent-manual
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/kernel/agent_manual/ANATOMY.md
  - src/lingtai/kernel/agent_manual/__init__.py
  - src/lingtai/kernel/agent_manual/MANUAL.md.tpl
  - src/lingtai/kernel/workdir.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - src/lingtai/kernel/base_agent/__init__.py
  - src/lingtai/tools/context/_molt.py
  - tests/test_agent_manual.py
  - pyproject.toml
maintenance: |
  <!-- CANONICAL-MAINTENANCE v2 BEGIN -->
  This component contract is governed by the root CONTRACT.md. Keep
  related_files complete and repo-relative: the paired ANATOMY.md, Core Ports,
  every production Adapter, selector, contract tests, and directly relevant
  component contracts belong here. Re-read this contract whenever a linked
  boundary changes. Update the Ports, affected Adapters, selector, contract
  tests, and this contract in the same change; update the paired Anatomy when
  structure or composition also changes; bump contract_version for a breaking
  Port-contract change. If code and contract disagree, treat the disagreement
  as a defect—do not silently rewrite the normative contract to match the
  implementation.
  Follow the root Anatomy/Contract pairing rule, report mismatches, and do not duplicate or auto-fix the rule here.
  <!-- CANONICAL-MAINTENANCE END -->
---
# Agent Manual

Stable entry: `lingtai.kernel.agent-manual.v1`.

## Purpose

Every agent working directory carries a generated `MANUAL.md` at its root: the
agent's own 说明书 — a progressive-disclosure operational-guide entry that
supplements the resident substrate section of the system prompt. It teaches
the agent (and any human reading over its shoulder) what each path in its
working directory is, who maintains it, how to edit it safely, how to read its
own status, and how the manual itself changes. This contract owns the manual's
generation mechanism; the exact content carve-out between the manual and the
resident substrate is deliberately deferred to a later iteration.

## Behavior

`ensure_agent_manual(layout_or_root, *, facts=None)` renders the packaged
template `MANUAL.md.tpl` (static sections + directory-map table + a
live-snapshot section filled from the caller-supplied facts dict) and writes
`<working_dir>/MANUAL.md` atomically (sibling temp file + rename). The
regeneration check is mechanical: the file is rewritten only when it is
missing or its head `template_version` differs from the packaged template's;
a version match is a strict no-op. The renderer is pure — facts in, text out —
so mount call sites gather facts and the renderer stays directly testable.

## Contract rules

1. `agent-manual.ownership.v1` — The kernel owns the manual: `MANUAL.md` is
   generated in full from `MANUAL.md.tpl`. There is **no** agent-side overlay,
   no `MANUAL.local.md`, and no local-append mechanism; content changes land
   as kernel template PRs, never as private per-agent overrides. Hand edits to
   a generated `MANUAL.md` are overwritten at the next template-version bump.
2. `agent-manual.versioning.v1` — The template head declares
   `template_version` (currently `agent-manual/v1`); the rendered file carries
   the same field, and staleness is decided by exact comparison of that field
   alone. A missing, unreadable, or unversioned existing file counts as stale.
3. `agent-manual.timing.v1` — Generation is checked at the context-rebuild
   moments only: `_perform_refresh`, agent molt (`_context_molt`), and
   `BaseAgent` construction (the path avatars reach). Every mount is
   fail-soft (`try/except`) — a manual failure never breaks refresh, molt, or
   construction — and the heartbeat loop never touches the manual.
4. `agent-manual.secrets.v1` — The renderer never reads `.secrets/` and never
   includes secret values: it may name the `.secrets/` path and its
   discipline, never content. The facts dict is scrubbed through the shared
   secret-key redaction (`workdir._redact_secrets`) before substitution, and
   the upstream facts collection uses only the manifest's safelisted `llm`
   block.
5. `agent-manual.paths.v1` — The manual's location is named by
   `WorkdirLayout.manual` (`<root>/MANUAL.md`); no other module retypes the
   path. The write is crash-atomic via `_fsutil.atomic_write_text`: a failed
   write leaves either the old file or none, never a partial.

## Contract tests

`tests/test_agent_manual.py` pins: first generation when missing; strict no-op
on a matching `template_version`; regeneration on a stale version; atomicity
(no partial file or temp litter on a failed write); live-snapshot rendering
from a facts dict; secret values never reaching the rendered file; the
directory-map table structure; and the absence of any overlay mechanism or
reference.

## Maintenance

Follow the canonical maintenance block in frontmatter. When the template
gains, loses, or renames sections, bump `template_version` in
`MANUAL.md.tpl`; the version compare is the only regeneration trigger, so an
unbumped content change silently never reaches existing agents.

---
name: soul-manual
description: >-
  Retained-path compatibility redirect for Soul's canonical package manual;
  this file intentionally contains no operational Soul guidance.
version: 1.2.0
last_changed_at: "2026-08-24T00:00:00Z"
legacy_redirect: src/lingtai/tools/soul/manual
redirect_marker: soul-manual-legacy-redirect-v1
redirect_target: src/lingtai/tools/soul/manual/SKILL.md
operational_content: false
related_files:
- src/lingtai/tools/soul/manual/SKILL.md
- src/lingtai/tools/soul/CONTRACT.md
maintenance: |
  Retain this historical path and its exact redirect marker until the installed
  manual compatibility contract is retired; never add operational guidance here.
---

# Soul Manual — retained-path redirect

This historical `intrinsic_skills/soul-manual` bundle is retained for path
compatibility only. It is **not** an operational manual and must never become a
second source of Soul guidance.

The sole operational content is the package manual at
`src/lingtai/tools/soul/manual/SKILL.md`. A manual installer may recognize this
file only after verifying the exact redirect markers in the frontmatter:
`legacy_redirect: src/lingtai/tools/soul/manual`, `redirect_marker: soul-manual-legacy-redirect-v1`,
`redirect_target: src/lingtai/tools/soul/manual/SKILL.md`, and
`operational_content: false`.
Resolve the canonical package source instead; do not copy or execute this
redirect body as the installed manual.

---
name: context-manual
legacy_redirect: src/lingtai/tools/context/manual
description: |
  Legacy source-tree redirect retained for the no-delete Context recut. It is not
  a manual owner and is never installed when the canonical Context package is
  present; read the package manual instead.
version: 2.1.1
last_changed_at: "2026-08-23T00:00:00Z"
related_files:
- src/lingtai/tools/context/manual/SKILL.md
- src/lingtai/agent.py
maintenance: |
  This retained tree is a documented redirect only. Keep its marker and the
  narrow installer allowlist aligned with the canonical Context package; never
  restore procedure content here.
---

# Context manual legacy redirect

`src/lingtai/tools/context/manual/` is the sole canonical source and the source
that `Agent._install_intrinsic_manuals` installs at
`.library/intrinsic/capabilities/context-manual/`. This retained intrinsic tree
exists only because deletion is outside this recut's authority. It is not a
second public manual, is not copied over the package manual, and must not gain
independent operational guidance.

Read [`src/lingtai/tools/context/manual/SKILL.md`](../../tools/context/manual/SKILL.md)
in the source tree, or call `context(action="manual", input={}, reasoning="...")`
at runtime.

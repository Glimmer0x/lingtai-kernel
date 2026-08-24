---
name: file-manual
description: "Compatibility redirect for the retained File manual path; the operational body is owned by the File package manual."
version: 0.4.0
tags: [files, file-manual, compatibility, redirect]
last_changed_at: "2026-08-24T00:00:00Z"
redirect: src/lingtai/tools/file/manual/SKILL.md
related_files:
- src/lingtai/tools/file/manual/SKILL.md
- src/lingtai/tools/file/ANATOMY.md
- src/lingtai/tools/file/CONTRACT.md
maintenance: |
  This retained legacy path is a compatibility marker, not an operational manual
  owner. Keep the package-owned File manual as the sole body source; update this
  marker only when the compatibility destination or owner route changes.
---

# Retained File Manual Compatibility Redirect

This legacy `file-manual` source path is retained so existing package/resource
lookups and documentation links do not disappear. It is **not** a second manual
body and must not be edited to teach File operations.

The sole operational authority is:

- `src/lingtai/tools/file/manual/SKILL.md`

The serialized installer maps that package-owned body to the established
`.library/intrinsic/capabilities/file-manual/SKILL.md` destination. The File
manual action prefers that legacy destination and accepts the candidate-era
`capabilities/file` destination only as a read-only transition fallback. If a
redirect marker is encountered at runtime, it is never returned as the manual
body; the package-owned body must be installed instead.

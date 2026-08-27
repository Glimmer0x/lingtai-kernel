---
name: tool-plugin-settings-reference
description: >
  Developer reference for opting one ToolPlugin or curated descriptor into the
  bounded generic settings contract without changing other families.
tags: [lingtai, system-manual, tool-plugin, settings, contract]
version: 1.0.0
last_changed_at: 2026-08-27T00:00:00Z
related_files:
  - src/lingtai/kernel/tool_plugin/ANATOMY.md
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/settings.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/tool_family/settings.py
  - src/lingtai/mcp_servers/ANATOMY.md
  - src/lingtai/mcp_servers/_plugin.py
  - tests/test_tool_settings_contract.py
maintenance: |
  Keep this progressive-disclosure reference aligned with the generic opt-in
  Port, controller, curated descriptor seam, and synthetic conformance tests.
  Owner-specific semantics belong in that owner's later PR and manual.
---
# ToolPlugin settings owner reference

Use this only when a later owner PR deliberately opts one family in. Leave
every unrelated `ToolPluginDeclaration` or `CuratedMcpPlugin` at `settings=None`.

## Declare

Create one frozen contract of specs. Each spec owns its canonical key, closed
kind, env, default, precedence, mutability, timing, sensitivity, and comment.
Keep enum/range/path/conditional and persistence policy in the owner.

## Bind

Inject `resolve`, `set`, and `reset` with the family. Return state with runtime
facts only and receipts with exact operation/key, commit/application states,
changed keys, and an optional closed code—never prose. Post-call exceptions are
`unknown`; committed pending or failure remains committed.

Use `public` only for metadata and values safe to inventory. Use `redacted` for
secrets: the controller then omits env, source, precedence, and authored comment
and projects fixed redaction markers. `opaque` is immutable or owner-only and
inventory-only.

## Prove

Test identity, source/defaults, invalid values, receipts, timing, redaction, and
the real schema. Keep every unrelated official and curated descriptor absent.

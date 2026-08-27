---
name: tool-plugin-settings-reference
description: >
  Developer reference for opting one tool family into bounded, read-only
  settings discovery without changing other families.
tags: [lingtai, system-manual, tool-family, settings]
version: 3.0.0
last_changed_at: 2026-08-27T00:00:00Z
related_files:
  - src/lingtai/kernel/tool_plugin/__init__.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/tool_family/CONTRACT.md
  - src/lingtai/tools/tool_family/__init__.py
  - src/lingtai/tools/tool_family/settings.py
  - src/lingtai/mcp_servers/ANATOMY.md
  - src/lingtai/mcp_servers/_plugin.py
  - tests/test_tool_settings_contract.py
maintenance: |
  Keep this provider guide aligned with the ToolFamily SHOW seam and its
  focused tests; each future provider's meaning and change procedure belong in
  that family's own manual.
---
# ToolFamily settings SHOW reference

Use this only in a later family-owner change; every production family currently
stays opted out.

## Opt in

1. Set `settings=True` on the `ToolPluginDeclaration` or `CuratedMcpPlugin`.
2. Pass a callable `settings_provider` to `ToolFamily`; it returns a fresh
   iterable of public `SettingRow` values and performs no configuration change.
3. Supply each row's key, effective value plus source (or bounded unavailable
   text), default when one exists, configurable flag, optional canonical
   env/config key, application timing when configurable, exact `manual_ref`,
   and sensitivity flag.
4. Put accepted values, precedence, and the real change/apply procedure in the
   family manual section named by `manual_ref`; the generic row does not own
   those policies.

## Read contract

`settings(input={})` is the only operation. Missing defaults are distinct from
JSON `null`; sensitive effective/default values render as `<redacted>` while
metadata and `manual_ref` remain visible.

Any provider exception, malformed row, or non-JSON display value returns one
fixed bounded failure with no partial rows or exception text. The complete
response is measured while rows are consumed and stops at 65,536 UTF-8 bytes;
oversize output becomes one fixed no-row failure.

## Verify

Run `tests/test_tool_settings_contract.py` plus the opted-in family's real
schema/dispatch/manual tests, and confirm all unrelated declarations remain
opted out.

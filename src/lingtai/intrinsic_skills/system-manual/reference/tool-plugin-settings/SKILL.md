---
name: tool-plugin-settings-reference
description: >
  Developer reference for opting one tool family into bounded, read-only
  settings discovery without changing other families.
tags: [lingtai, system-manual, tool-family, settings]
version: 4.0.1
last_changed_at: 2026-08-28T00:00:00Z
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

Use this for one bounded family-owner change at a time. System is currently the
only production family opted in; every later owner remains opted out until its
own vertical change.

## Opt in

1. Set `settings=True` on the `ToolPluginDeclaration` or `CuratedMcpPlugin`.
2. Bind a callable `settings_provider` to `ToolFamily`; the declaration opt-in
   plus this bound provider makes SHOW available. The presence of an owner
   document does not opt a family in.
3. The provider returns a fresh
   iterable of public `SettingRow` values and performs no configuration change.
4. Supply exactly `key`, `current`, `default`, `configurable`, and `comment`.
   `comment` is the exact family-manual section pointer. Use `None` when the
   owner has no meaningful default; raise if the current value is unavailable.
5. Put meaning, accepted values, source and precedence, config/environment key,
   apply timing, and the real change procedure in that manual section. Do not
   copy those details into each row.
6. Set the private `_sensitive=True` flag only when `current` and `default`
   must both render as `<redacted>`; the flag itself is never projected.

System's `settings/system.json` is closed and versioned. A v1 document is exactly the cache-miss-budget source. A v2 document may carry any subset of the
seven ordinary System runtime-policy fields, the cache field, and Notification's
file-layer cap. It may be absent; documented defaults then apply and the
declaration-bound SHOW provider remains available. File presence still does not
opt the family into SHOW.

## Read contract

`settings(input={})` is the only operation. Normal success is exactly this
shape, with no projected `status` or extra row metadata:

```json
{"settings":[{"key":"example.timeout","current":30,"default":15,"configurable":true,"comment":"example-manual#timeout"}]}
```

Any provider exception, unavailable current, malformed row, or non-JSON display
value returns one fixed bounded failure with no partial rows or exception text.
The complete response is measured while rows are consumed and stops at 65,536
UTF-8 bytes; oversize output becomes one fixed no-row failure.

## Verify

Run `tests/test_tool_settings_contract.py` plus the opted-in family's real
schema/dispatch/manual tests, and confirm all unrelated declarations remain
opted out.

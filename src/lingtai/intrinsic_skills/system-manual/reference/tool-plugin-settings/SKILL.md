---
name: tool-plugin-settings-reference
description: >
  Developer reference for opting one ToolPlugin or curated descriptor into a
  bounded, read-only settings inventory without changing other families.
tags: [lingtai, system-manual, tool-plugin, settings, contract]
version: 2.0.0
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
  Owner-specific meaning and change procedures belong in that owner's later PR
  and manual; never turn this generic reference into a mutation API.
---
# ToolPlugin settings SHOW owner reference

Use this only when a later owner PR deliberately opts one family in. Leave
every unrelated `ToolPluginDeclaration` or `CuratedMcpPlugin` at `settings=None`.

## Product boundary

`settings` is pure SHOW and progressive disclosure. It accepts only
`input={}` and returns current effective facts plus concise configuration
metadata. It never sets, resets, persists, refreshes, rebuilds, or relaunches
anything. The generic contract must not read or write environment variables,
configuration files, launchers, or any other owner technology.

An agent that wants a real change follows the canonical Shell/File/config/
launcher procedure documented by the owner, performs the documented refresh,
rebuild, or relaunch, and calls `settings(input={})` again to verify the new
effective state.

## Declare

Create one frozen contract of specs. Each spec owns its canonical key, closed
kind, `configurable` boolean, optional canonical `env`, bounded ordered
`precedence`, `sensitivity`, optional default, and required `manual_ref`. A
configurable spec also declares `application_timing`. `configurable=true`
means a canonical external owner route exists; it never means the `settings`
action can change the value. A non-configurable spec has neither `env` nor
`application_timing`, so its row cannot imply a nonexistent change route.

`manual_ref` is a bounded, non-empty pointer to the exact owning manual and
section. It replaces free-form inventory comments. The referenced owner
section—not the inventory row—must document the setting's meaning, accepted
values, precedence, canonical change path, and apply timing. Every owner PR
must test that each declared reference resolves to a real section.

Declarations are deliberately technology-neutral. The closed value kinds are
`boolean`, `integer`, `number`, `string`, `string-list`, and `opaque`; mappings
and recursive values are refused. Integers are limited to the inclusive range
`-9,223,372,036,854,775,807` through `9,223,372,036,854,775,807`. Strings are
limited to 16,384 characters and 16,384 UTF-8 bytes. String lists are limited
to 1,024 items and 1,048,576 aggregate UTF-8 bytes. A contract has at most
1,024 specs, and declaration metadata fields have at most 1,024 characters.
Precedence has at most 32 entries. Keep enum, range, path, conditional, and
persistence policy in the owner.

## Resolve

Inject only `resolve(spec) -> SettingState`. An available state carries the
current effective value and a source declared in the spec's precedence list.
An unavailable state carries only the closed `SETTING_UNAVAILABLE` diagnostic.
Wrong types, wrong value kinds, undeclared sources, and owner exceptions fail
loud as `OWNER_RESOLVE_FAILED`, without exposing exception text or fabricating
a value.

## Read

Opt-in injects one reserved `settings` action immediately before `manual` (or
last if no manual exists). `settings(input={})` resolves every declared setting
fresh and returns rows containing `key`, `available`, `value_kind`,
`configurable`, `precedence`, `sensitivity`, `manual_ref`, and `has_default`,
plus, when applicable, `application_timing`, `env`, `source`, effective value,
default, or a bounded availability/resolve diagnostic.

Use `public` only for safe values. For `redacted`, current and default values
become the fixed `<redacted>` marker, while safe progressive-disclosure
metadata—including source, precedence, env, timing, configurability,
`has_default`, and `manual_ref`—remains visible.

The complete response must fit in 65,536 UTF-8 bytes when encoded as canonical
JSON with sorted keys, no ASCII escaping, and separators `,` and `:`. A larger
response returns only the bounded `SETTINGS_RESPONSE_TOO_LARGE` failure with
`max_bytes=65536`; it never truncates values or returns a partial inventory.

Because `manual` and `settings` can both have strict `{}` input schemas, the
existing aggregate schema uses `anyOf` for an opted-in family. Do not broaden
schema composition in an owner PR. The first production owner must repeat the
live provider probe for its actual composed schema and record the evidence.

## Prove

Test declaration identity, fresh resolution, source/default projection,
unavailable and malformed owner results, redaction with safe metadata retained,
the 65,536-byte whole-response refusal, exact strict-empty input, and the real
model-facing schema. Prove every `manual_ref` target exists and its owner
section contains the required change guidance. Keep every unrelated official
and curated descriptor absent.

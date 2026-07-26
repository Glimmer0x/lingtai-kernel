---
name: notification-manual
description: >
  Notification filesystem and standalone notification tool router for LingTai.
  Read this when using notification(action='manual'|'check'|'dismiss_channel'|
  'dismiss_event'|'dismiss_ref') with nested input, interpreting
  `.notification/<channel>.json`, or deciding between producer-specific handling
  and safe mirror dismissal. Routes channel/sync mechanics and dismissal safety
  into nested references; large-result compaction remains owned by summarize-manual.
version: 0.5.0
tags: [lingtai, notifications, channels, dismiss, manual, force, stale, nudge]
last_changed_at: "2026-07-26"
related_files:
- src/lingtai/tools/notification/__init__.py
- src/lingtai/tools/notification/schema.py
- src/lingtai/tools/_settings.py
- src/lingtai/intrinsic_skills/notification-manual/reference/channel-model/SKILL.md
- src/lingtai/intrinsic_skills/notification-manual/reference/dismissal-safety/SKILL.md
maintenance: |
  Tracks the routed source/resources it summarizes; update when the underlying capability or its sub-references change.
---

# Notification Manual — Router

LingTai notifications are a filesystem protocol: producers publish allowlisted
`.notification/<channel>.json` surfaces, and the kernel exposes their current
model-visible state. The always-available `notification` tool is the sole
agent-callable home for reading and clearing those surfaces. `system` has no
notification or dismiss alias; it still owns `summarize` because context hygiene
is not a notification operation.

## Public call shape

Every public call has an explicit root `action` and nested `input`; the Agent
schema may additionally carry optional root `reasoning`. Reasoning is never
nested in `input`.

| Action | Canonical call | Use |
|---|---|---|
| `manual` | `notification(action='manual', input={})` | Return this installed router body. Strictly read-only. |
| `check` | `notification(action='check', input={})` | Request the live notification payload. The handler returns a placeholder and the kernel stamps `_meta.agent_meta.notifications.attention` plus `_meta.agent_meta.guidance.transient` onto the result. |
| `dismiss_channel` | `notification(action='dismiss_channel', input={'channel': 'soul'})` | Clear one dismissible channel mirror whole. |
| `dismiss_event` | `notification(action='dismiss_event', input={'event_id': '...', 'channel': 'system'})` | Remove one matching system event. `channel` defaults to `system`. |
| `dismiss_ref` | `notification(action='dismiss_ref', input={'ref_id': '...', 'channel': 'system'})` | Remove matching system events by producer reference. `channel` defaults to `system`. |

There is no aggregate `dismiss` action. After handling a notification, use the
narrowest correct producer-specific or atomic dismiss action and end the turn;
do not voluntarily call `check` again merely to confirm the clear.

## Action inputs

`check` and `manual` accept only `{}`. `dismiss_channel` requires `channel` and
may also carry `force` and `reason`. `dismiss_event` requires `event_id` and
`dismiss_ref` requires `ref_id`; both may carry `channel`, `force`, and `reason`.
These fields are action-owned: flat fields, cross-action fields, omitted action,
`parameters`, and compatibility aliases are invalid.

`force=true` is only for knowingly clearing a stale or producer-guarded mirror;
it never mutates producer state or overrides protected channels. A
post-molt dismissal requires `reason='<continue|defer|obsolete>: ...'`.

## Installed manual retrieval

`notification(action='manual', input={})` reads only:

```text
<agent>/.library/intrinsic/capabilities/notification-manual/SKILL.md
```

Success retains the established `status`, `notification_manual`, and
`manual_path` fields. A missing installed file returns `status: degraded`, an
empty `notification_manual`, the same fixed `manual_path`, and an actionable
`error` naming an initializer or capability-install problem. It never falls back
to a source checkout and never touches `.notification/`, the Notification Store,
producer state, delivery fingerprints, or acknowledgement state.

## Settings evidence

Every success and error also reports fresh `current_setting` evidence from the
Agent-owned `settings/notification.json` placeholder. The only valid content is
`{"schema_version": 1}`. Missing, valid, byte-distinct rewrites, and invalid
content are observable metadata only; they never select, enable, or alter a
notification action. Settings diagnostics expose only the agent-relative path
hint, bounded revision/hash evidence, and bounded errors, never secrets,
absolute paths, or file contents.

## Nested reference catalog

```yaml
- name: notification-manual-channel-model
  location: reference/channel-model/SKILL.md
  description: |
    Nested notification-manual reference for the filesystem channel protocol,
    allowlist, envelopes and instructions, nudge routing, kernel sync, voluntary
    check behavior, and producer canonical-state versus mirror boundaries.
- name: notification-manual-dismissal-safety
  location: reference/dismissal-safety/SKILL.md
  description: |
    Nested notification-manual reference for atomic dismissal, producer-specific
    verbs, stale-version and force rules, protected channels, post-molt
    acknowledgement, and legacy large_tool_result reminder escape hatches.
```

## Routing table

| Need / keywords | Read |
|---|---|
| Channel names; `.notification/*.json`; allowlist; `mcp.` channels; envelope fields; `instructions`; nudge/update checks; `_meta.agent_meta.notifications.attention`; voluntary `check`; producer state versus mirror | `reference/channel-model/SKILL.md` |
| Which dismiss action; producer-specific handling; guarded/stale mirror; `force`; protected `goal`; post-molt reason; legacy `large_tool_result` event | `reference/dismissal-safety/SKILL.md` |
| Tool-result ranking, digest quality, `system(action='summarize')`, recovery by `tool_call_id`, summarize versus molt | `../system-manual/reference/summarize-manual/SKILL.md` |
| Active goal source-of-truth and cancellation/completion | `../system-manual/reference/goal-manual/SKILL.md` |
| Runtime/kernel update nudges | `../system-manual/reference/runtime-update-checks/SKILL.md` |

## Safety boundaries to keep resident

- `check` is the notification-state read; `manual` is documentation retrieval
  only. Neither writes notification state.
- Generic dismiss clears a notification mirror, never producer-owned canonical
  state. Prefer the producer's own verb when one exists.
- `force=true` does not override protected source-of-truth channels and never
  mutates producer state.
- Large tool results are ranked under
  `_meta.agent_meta.agent_state.current_tool_result_chars`, not emitted as new
  notifications. Follow `../system-manual/reference/summarize-manual/SKILL.md`;
  do not invent a second summarization procedure here.

## Why the boundary is split this way

The filesystem protocol lets in-process and external producers publish one
current surface without sharing a queue; atomic action names make the clearing
target explicit; producer guards keep a mirror clear from being mistaken for
handling source-of-truth state.

---
name: notification-manual
description: >
  Notification filesystem and standalone notification tool router for LingTai.
  Read this when using notification(action='manual'|'check'|'dismiss_channel'|
  'dismiss_event'|'dismiss_ref') with its action+input+reasoning envelope,
  interpreting `.notification/<channel>.json`,
  or deciding between producer-specific handling and safe mirror dismissal.
  Routes channel/sync mechanics and dismissal safety into nested references;
  large-result compaction remains owned by summarize-manual.
version: 0.5.0
tags: [lingtai, notifications, channels, dismiss, manual, force, stale, nudge]
last_changed_at: "2026-07-27T00:00:00Z"
related_files:
- src/lingtai/tools/notification/__init__.py
- src/lingtai/tools/notification/schema.py
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

## Quick start

Every call takes three fields: `action`, the strict `input` object for that
action, and `reasoning`. Arguments live inside `input` — never at the root.

| Action | Use |
|---|---|
| `notification(action='manual', input={}, reasoning=...)` | Return this installed router body. Strictly read-only: it neither reads nor changes notification state. |
| `notification(action='check', input={}, reasoning=...)` | Request the live notification payload. The handler returns a placeholder and the kernel stamps `_meta.agent_meta.notifications.attention` plus `_meta.agent_meta.guidance.transient` onto the result. |
| `notification(action='dismiss_channel', input={'channel': ..., 'force': null, 'reason': null}, reasoning=...)` | Clear one dismissible channel mirror whole. |
| `notification(action='dismiss_event', input={'event_id': ..., 'channel': null, 'force': null, 'reason': null}, reasoning=...)` | Remove one matching system event; a null `channel` means `system`. |
| `notification(action='dismiss_ref', input={'ref_id': ..., 'channel': null, 'force': null, 'reason': null}, reasoning=...)` | Remove matching system events by producer reference; a null `channel` means `system`. |

Optional fields are declared as required-but-nullable, which is how a strict
schema expresses "optional". Pass `null` when you do not want to supply one;
null is treated exactly like omitting it, so `channel: null` still defaults to
`system` and `reason: null` does **not** satisfy the post-molt acknowledgement
requirement.

Each action accepts only its own fields. `event_id` and `ref_id` are not part of
`dismiss_channel`'s input at all — sending one there is rejected before any
notification state is read or written, so use `dismiss_event` / `dismiss_ref`
for a single event.

There is no aggregate `dismiss` action. After handling a notification, use the
narrowest correct producer-specific or atomic dismiss action and end the turn;
do not voluntarily call `check` again merely to confirm the clear.

## Root `summarize`

`summarize` is a root envelope boolean, not an action argument, and it is
absent/false by default. Notification is a **short-result** family: `check`
returns a small placeholder and the dismiss actions return compact receipts, so
`summarize` is available but normally unnecessary — leave it false. Keep it
false for `manual` in particular, so exact procedures and constraints are not
summarized away. Note this is unrelated to `context(action='summarize')`, which
is the separate action for compacting a large tool result.

## Installed manual retrieval

`notification(action='manual', input={})` reads only:

```text
<agent>/.library/intrinsic/capabilities/notification-manual/SKILL.md
```

Success returns exactly `status`, `notification_manual`, and `manual_path`. A
missing installed file returns `status: degraded`, an empty
`notification_manual`, the same fixed `manual_path`, and an actionable `error`
naming an initializer or capability-install problem. It never falls back to a
source checkout and never touches `.notification/`, the Notification Store,
producer state, delivery fingerprints, or acknowledgement state.

## Nested reference catalog

```yaml
- name: notification-manual-channel-model
  location: reference/channel-model/SKILL.md
  description: |
    Nested notification-manual reference for the filesystem channel protocol,
    allowlist, envelopes and instructions, nudge routing, kernel sync, voluntary
    check behavior, and producer canonical-state versus mirror boundaries. Read
    this when interpreting or producing notification payloads.
- name: notification-manual-dismissal-safety
  location: reference/dismissal-safety/SKILL.md
  description: |
    Nested notification-manual reference for atomic dismissal, producer-specific
    verbs, stale-version and force rules, protected channels, post-molt
    acknowledgement, and legacy large_tool_result reminder escape hatches. Read
    this before clearing notification state or diagnosing a refusal.
```

## Routing table

| Need / keywords | Read |
|---|---|
| Channel names; `.notification/*.json`; allowlist; `mcp.` channels; envelope fields; `instructions`; nudge/update checks; `_meta.agent_meta.notifications.attention`; voluntary `check`; producer state versus mirror | `reference/channel-model/SKILL.md` |
| Which dismiss action; producer-specific handling; guarded/stale mirror; `force`; protected `goal`; post-molt reason; legacy `large_tool_result` event | `reference/dismissal-safety/SKILL.md` |
| Tool-result ranking, digest quality, `context(action='summarize')`, recovery by `tool_call_id`, summarize versus molt | `../context-manual/reference/summarize-manual/SKILL.md` |
| Active goal source-of-truth and cancellation/completion | `../system-manual/reference/goal-manual/SKILL.md` |
| Runtime/kernel update nudges | `../system-manual/reference/runtime-update-checks/SKILL.md` |

## Safety boundaries to keep resident

- `check` is the notification-state read; `manual` is documentation retrieval
  only. Neither writes notification state.
- Generic dismiss clears a notification mirror, never producer-owned canonical
  state. Prefer the producer's own verb when one exists.
- `force=true` is for knowingly clearing a stale or guarded mirror. It does not
  override protected source-of-truth channels and never mutates producer state.
- Large tool results are ranked under
  `_meta.agent_meta.agent_state.current_tool_result_chars`, not emitted as new
  notifications. Follow `../context-manual/reference/summarize-manual/SKILL.md`;
  do not invent a second summarization procedure here.

## Why the boundary is split this way

The filesystem protocol lets in-process and external producers publish one
current surface without sharing a queue; atomic action names make the clearing
target explicit; producer guards keep a mirror clear from being mistaken for
handling source-of-truth state.

---
name: notification-manual
description: >
  Migration redirect for the retained Notification manual source path. The
  canonical manual now ships with the always-on official `notification`
  declaration and is installed from the owning tool package.
version: 0.10.1
tags: [lingtai, notifications, migration, redirect]
last_changed_at: "2026-08-23T00:00:00Z"
related_files:
- src/lingtai/tools/notification/manual/SKILL.md
- src/lingtai/tools/notification/__init__.py
- src/lingtai/kernel/tool_plugin/CONTRACT.md
maintenance: |
  Retained only as migration material; update this redirect if the canonical
  Notification manual destination changes.
---

# Notification Manual — Migration Redirect

This source-tree manual is retained for migration and source-history
compatibility only. It is **not** a second installed Notification capability
manual and must not be copied into the agent library alongside the canonical
manual.

Read the canonical Notification manual here:

```text
src/lingtai/tools/notification/manual/SKILL.md
```

At runtime, the official `notification` declaration installs that manual at:

```text
<agent>/.library/intrinsic/capabilities/notification/SKILL.md
```

Use `notification(action='manual', input={}, reasoning='...')` to retrieve the
installed body. The action is read-only and does not inspect or mutate
notification state. The old `notification-manual` source path is skipped by
manual installation so there is exactly one Notification manual destination.

The public `notification` tool is an always-on official host-plugin mount. It
is not removed by `disable=['notification']` or by a
`capabilities: {'notification': null}` opt-out spelling; those inputs are
retained only for compatibility with capability-shaped manifests. Its Core
state remains behind the narrow declared host port, and the package owns no
second claim, schema, handler, or producer-state implementation.

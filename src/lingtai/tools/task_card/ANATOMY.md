---
related_files:
  - src/lingtai/tools/task_card/CONTRACT.md
  - src/lingtai/tools/task_card/__init__.py
  - src/lingtai/tools/task_card/manual/SKILL.md
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/mcp_servers/telegram/task_card/ANATOMY.md
  - src/lingtai/mcp_servers/telegram/manager.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - tests/test_task_card_controller.py
  - tests/test_telegram_toolfamily_ltpv2.py
  - tests/test_telegram_task_card_programmable.py
maintenance: |
  Keep related_files repo-relative, duplicate-free, and linked to real files.
  Keep this Anatomy reciprocal with its paired CONTRACT.md and manual. Update
  this file in the same change as any ownership, file-path, lifecycle, or
  projection-boundary change.
---
# Intrinsic Task Card Anatomy

The intrinsic `task_card` capability owns one agent-local declarative artifact
under `<workdir>/taskcard/` and nothing else. It is producer-first and
channel-neutral: it runs a renderer, writes `taskcard/taskcard.md`, and writes
`taskcard/status` as exact `active` or `inactive`. It does not own Telegram,
Feishu, portals, chat IDs, retry policy against a transport, or any resident
message state. Normative promises live in [`CONTRACT.md`](CONTRACT.md).

## Components

- `__init__.py` — the full capability owner: schema/description, one-watch
  lifecycle, renderer execution, atomic file writes, error/limit notifications,
  and `setup(agent)` registration.
- `manual/SKILL.md` — the progressive-disclosure manual for renderer authors
  and lifecycle use.

## Connections

- `setup(agent)` registers the public `task_card` tool through
  `lingtai.tools.registry`.
- `lifecycle._stop` calls `shutdown_for_agent_stop()` so a stopping agent
  writes `inactive` and joins the watch thread best-effort.
- Telegram is only a consumer: `TelegramManager` reads
  `<workdir>/taskcard/status` and `<workdir>/taskcard/taskcard.md` and projects
  them separately. The intrinsic capability never calls back into Telegram.

## Composition

- Parent: [`src/lingtai/tools/ANATOMY.md`](../ANATOMY.md)
- Paired contract: [`CONTRACT.md`](CONTRACT.md)
- Consumer-specific projection rules: `src/lingtai/mcp_servers/telegram/`

## State

- `<workdir>/taskcard/status` — exact `active` or `inactive`
- `<workdir>/taskcard/taskcard.md` — the full rendered body
- In-memory only: one active watch, its thread, last valid body/timestamp, and
  deduped error/limit bookkeeping

## Notes

- Atomic ordering is the structural point of this unit: write the body fully
  before activation, update the body by atomic replace, and write `inactive`
  before stopping.
- Missing, invalid, or inactive producer state is a consumer concern. This
  intrinsic capability only writes the artifact truthfully.

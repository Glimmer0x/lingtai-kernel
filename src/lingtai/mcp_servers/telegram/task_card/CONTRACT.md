---
name: telegram-task-card-projection
contract_version: 4
root_contract: CONTRACT.md
related_files:
  - src/lingtai/mcp_servers/telegram/task_card/ANATOMY.md
  - src/lingtai/mcp_servers/telegram/task_card/resident.py
  - src/lingtai/mcp_servers/telegram/task_card/SKILL.md
  - src/lingtai/mcp_servers/telegram/manager.py
  - src/lingtai/mcp_servers/telegram/service.py
  - src/lingtai/mcp_servers/telegram/server.py
  - src/lingtai/tools/task_card/CONTRACT.md
  - pyproject.toml
  - tests/test_telegram_task_card_programmable.py
  - tests/test_telegram_task_card_toggle.py
  - tests/test_telegram_task_card_event_tail.py
  - tests/test_mcp_skill_manuals.py
maintenance: |
  This component contract is governed by the root CONTRACT.md. Keep related
  files complete and repo-relative, keep the paired Anatomy/manual reciprocal,
  and update Telegram tests plus the intrinsic producer contract together when
  the projection boundary changes.
---
# Telegram Task Card Projection

## Purpose

Own Telegram's resident Task Card state and its read-only projection of the
intrinsic declarative Task Card artifact. Telegram-specific consuming semantics
live here; the public producer contract lives in
`src/lingtai/tools/task_card/CONTRACT.md`.

## Behavior

1. Telegram owns one tracked resident Task Card target per account+chat and
   composes two independent channels into it: `automatic` and `programmable`.
2. The programmable channel is read-only with respect to the intrinsic
   producer. It reads `<workdir>/taskcard/status` and `<workdir>/taskcard/taskcard.md`.
3. Telegram reads the programmable body only when `taskcard/status` is exactly
   `active`. Missing status, any non-`active` content, missing body, or blank
   body is a no-op.
4. A no-op preserves the last valid programmable Telegram frame. Telegram must
   not clear or replace the resident message just because the producer files are
   temporarily missing or invalid.
5. Projection is diff-only. If the body bytes match the committed programmable
   frame, Telegram performs no transport update.
6. When the Telegram `/taskcard` setting is off, presentation is suppressed.
   Automatic mechanics continue, and hidden programmable finalize still clears
   the committed programmable slot internally so a stale frame cannot resurface
   after re-enable.
7. Telegram transport, resident replacement, edit-in-place behavior, and the
   automatic event-tail channel remain Telegram-owned concerns and are outside
   the intrinsic producer contract.

## Port

Internal resident/projector boundary owned by `TaskCardResident` and consumed by
`TelegramManager`. There is no public MCP `task_card` family in this component.

## Adapters

- Filesystem reader for `<workdir>/taskcard/status` and `taskcard/taskcard.md`
- Telegram transport adapter in `TelegramManager`
- Durable Telegram account state for tracked resident message ids

## Contract rules

1. Telegram must not expose a public MCP `task_card` tool from `server.py`.
2. Programmable projection must remain read-only; no Telegram code may rewrite
   the intrinsic producer files.
3. Missing/invalid/inactive producer state is a no-op, not an implicit clear.
4. Diff-only comparison is against the committed programmable frame, not the
   composed resident text.
5. The automatic Task Card behavior remains independent of the programmable
   file projector.
6. This package's manual and governed docs remain explicitly packaged through
   `pyproject.toml`.

## Tests

- `tests/test_telegram_task_card_programmable.py` covers active projection,
  diff-only updates, inactive/no-op handling, and last-good preservation.
- `tests/test_telegram_task_card_toggle.py` covers toggle suppression and the
  hidden-finalize clear semantics.
- `tests/test_telegram_task_card_event_tail.py` continues to cover the automatic
  channel independently.
- `tests/test_mcp_skill_manuals.py` covers packaged docs for this subpackage.

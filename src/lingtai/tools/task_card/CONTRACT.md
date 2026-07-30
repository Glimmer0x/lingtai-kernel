---
name: intrinsic-task-card
contract_version: 1
root_contract: CONTRACT.md
related_files:
  - src/lingtai/tools/task_card/ANATOMY.md
  - src/lingtai/tools/task_card/__init__.py
  - src/lingtai/tools/task_card/manual/SKILL.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/registry.py
  - src/lingtai/kernel/base_agent/lifecycle.py
  - src/lingtai/mcp_servers/telegram/task_card/CONTRACT.md
  - src/lingtai/mcp_servers/telegram/manager.py
  - tests/test_task_card_controller.py
  - tests/test_telegram_toolfamily_ltpv2.py
  - tests/test_telegram_task_card_programmable.py
maintenance: |
  This component contract is governed by the root CONTRACT.md. Keep related
  files complete and repo-relative, keep the paired Anatomy/manual reciprocal,
  and update tests plus consumer docs in the same change when this producer
  contract moves.
---
# Intrinsic Task Card

## Purpose

Own the public model-facing `task_card` capability as a channel-neutral,
producer-first intrinsic tool. The capability maintains one agent-local
declarative artifact and one active watch per agent.

## Behavior

1. The capability owns exactly two files under the agent working directory:
   `taskcard/status` and `taskcard/taskcard.md`.
2. `start` validates a Python renderer path contained within the agent working
   directory, runs it synchronously, requires non-empty stdout, writes the full
   body atomically to `taskcard/taskcard.md`, then atomically writes
   `taskcard/status` as exact `active`, and only then starts the watch thread.
3. `retry` reruns the renderer for the active watch. On success it atomically
   replaces only `taskcard/taskcard.md`; `status` remains `active`.
4. `stop` and agent shutdown write exact `inactive` before stopping the updater.
   The last body remains on disk.
5. At most one watch may be active per agent. A second `start` fails closed.
6. The capability is channel-neutral. It MUST NOT own transport-specific
   concepts such as Telegram chat/message IDs, API retries, or consumer
   recovery policy.
7. Renderer execution failures after a watch exists preserve the last valid body
   and emit deduped `task_card.error` and `recovered` notifications. Refresh
   exhaustion emits one `task_card.limit` notification keyed by watch and limit.
8. Missing, invalid, or inactive producer state is outside this contract.
   Consumers decide what those states mean.

## Port

Public LTP-v2 family root `task_card` with actions `start`, `inspect`, `retry`,
`stop`, and `manual`.

## Adapters

- Renderer subprocess: `sys.executable <renderer>` with `cwd` set to the agent
  working directory.
- Filesystem artifact writer: atomic temp-file write + `fsync` + `os.replace`.
- Consumer example only: `TelegramManager` reads the artifact and projects it;
  that consuming behavior is not part of this contract.

## Contract rules

1. The renderer path must resolve inside the agent working directory after
   symlink resolution.
2. `taskcard/taskcard.md` must never be partially visible to a consumer.
3. Activation order is strict: body first, then `active`.
4. Deactivation order is strict: write `inactive` before stopping the updater.
5. The tool result for `start`/`inspect`/`retry`/`stop` must report the exact
   artifact paths and current `status_value`.
6. `manual` must remain discoverable from both this contract and the paired
   Anatomy.

## Tests

- `tests/test_task_card_controller.py` covers intrinsic registration,
  exact paths, atomic ordering, one-watch enforcement, failure/recovery, and
  stop semantics.
- `tests/test_telegram_toolfamily_ltpv2.py` covers the strict public family
  schema plus intrinsic refresh-limit behavior.
- `tests/test_telegram_task_card_programmable.py` covers Telegram's read-only
  consumer semantics against this producer contract.

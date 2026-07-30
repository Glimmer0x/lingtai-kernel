---
name: intrinsic-task-card
contract_version: 2
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

1. The capability owns exactly two artifact files under the agent working
   directory: `taskcard/status` and `taskcard/taskcard.md`. It additionally
   owns one persisted agent-wide configuration file, `taskcard/taskcard.json`
   (see rule 9), which is policy input, not producer output.
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
9. `taskcard/taskcard.json` holds optional `interval_s`, `timeout_s`, and
   `max_refreshes` fields. Built-in defaults are `interval_s: 5`, `timeout_s:
   10` (one renderer execution, not the watch's total lifetime), and
   `max_refreshes: 2000`; a configured value overrides the built-in default for
   its own field only. `start` resolves each of the three fields independently:
   an omitted field uses the configured (or built-in) default; an explicit
   `timeout_s`/`max_refreshes` is a safety ceiling request and is silently
   `min`-clamped to the configured ceiling (it may lower, never exceed, that
   ceiling); an explicit `interval_s` has no ceiling at all — only the
   pre-existing absolute floor of 1 second applies, so a slower/safer explicit
   cadence is always honored even when it configures above the default.
10. Config validation is strict and per-field: `interval_s`/`timeout_s` must be
    a non-boolean finite number at or above their floor (1 and 0.1 respectively)
    and `max_refreshes` must be a non-boolean positive `int`; an invalid or
    missing field falls back to its own built-in default without discarding
    valid sibling fields, and a config file that fails to parse as a JSON
    object falls back to all built-in defaults. No malformed input can produce
    a larger effective ceiling or a faster effective floor than the built-in
    defaults allow.
11. The first time `start` resolves configuration and finds no
    `taskcard/taskcard.json`, it performs a one-way migration: if
    `telegram/taskcard.json` (the retired Telegram-owned reverse-channel
    design's persisted state) holds a valid positive-integer `max_refreshes`
    that differs from that legacy design's own untouched default (1000),
    that value is written into a new `taskcard/taskcard.json` (with the
    built-in `interval_s`/`timeout_s` defaults) and used for this resolution.
    Once `taskcard/taskcard.json` exists, `telegram/taskcard.json` is never
    read again for intrinsic policy — this capability never gains an ongoing
    runtime dependence on Telegram. A missing, invalid, or untouched-default
    legacy value does not migrate a ceiling: the built-in defaults are
    written into a new `taskcard/taskcard.json` instead, exactly as if no
    legacy state existed, so this first resolution always creates
    `taskcard/taskcard.json` — migrated or built-in — and the gate closes for
    every agent, not only the ones with a genuinely customized legacy value.
    The untouched-default exclusion matters because ordinary
    `/taskcard on|off|N` Telegram commands persist that file's three legacy
    fields together to change unrelated presentation settings, leaving
    `max_refreshes` at its own never-customized default — migrating that
    incidental value would silently cap most ordinary agents below the new
    built-in default instead of leaving them on it.
12. Agents SHOULD start a watch proactively — without being asked — when a
    human is following meaningful long-running, multi-step, or parallel work
    and a durable progress view would materially help; they SHOULD NOT start
    one for quick single-step work, as ritual, or when they cannot keep the
    rendered body truthful and current. This is agent usage guidance, not a
    runtime-enforced precondition.

## Port

Public LTP-v2 family root `task_card` with actions `start`, `inspect`, `retry`,
`stop`, and `manual`.

## Adapters

- Renderer subprocess: `sys.executable <renderer>` with `cwd` set to the agent
  working directory.
- Filesystem artifact writer: atomic temp-file write + `fsync` + `os.replace`.
- Filesystem config reader: plain read of `taskcard/taskcard.json` (no fsync;
  read-only in the steady state) plus the one-way legacy-migration writer
  described in Behavior rule 11.
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
7. Configuration is resolved fresh from `taskcard/taskcard.json` on every
   `start`; `inspect`/`retry`/`stop` act only on values already fixed onto the
   existing watch and never re-resolve configuration.
8. The legacy migration in Behavior rule 11 MUST NOT become an ongoing read
   path: it is gated strictly on `taskcard/taskcard.json` not yet existing, not
   on its content being valid.

## Tests

- `tests/test_task_card_controller.py` covers intrinsic registration,
  exact paths, atomic ordering, one-watch enforcement, failure/recovery, stop
  semantics, configured defaults/ceilings (including the omitted-value and
  lower-not-bypass cases), per-field config validation, the one-way
  legacy-migration fallback, and the proactive-use guidance carried in the
  description, manual, and this contract's Behavior rule 12.
- `tests/test_telegram_toolfamily_ltpv2.py` covers the strict public family
  schema plus intrinsic refresh-limit behavior.
- `tests/test_telegram_task_card_programmable.py` covers Telegram's read-only
  consumer semantics against this producer contract.

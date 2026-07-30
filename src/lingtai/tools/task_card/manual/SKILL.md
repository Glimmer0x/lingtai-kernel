---
related_files:
- src/lingtai/tools/task_card/__init__.py
- src/lingtai/tools/task_card/ANATOMY.md
- src/lingtai/tools/task_card/CONTRACT.md
maintenance: |
  Keep this manual aligned with the intrinsic task_card capability's actual
  action surface, the exact taskcard/status and taskcard/taskcard.md file
  contract, and the one-card-per-agent lifecycle. Update it with the paired
  Anatomy/Contract whenever the renderer contract, file paths, or stop/order
  semantics change.
---

# task_card manual

Use `task_card` to maintain one agent-local declarative Task Card artifact.

The capability owns exactly two files under your working directory:

- `taskcard/status`
- `taskcard/taskcard.md`

Actions are `start`, `inspect`, `retry`, `stop`, and `manual`.

`start` runs a Python renderer under your working directory. The renderer must
exit `0` and print a nonempty full body to stdout; that body is written to
`taskcard/taskcard.md`. After the body is written atomically, the capability
writes `taskcard/status` as the exact text `active`.

`retry` reruns the renderer now for the same watch. Successful updates replace
only `taskcard/taskcard.md` atomically; the status stays `active`.

`stop` writes `taskcard/status` as `inactive` before stopping the updater. The
last body stays on disk. Consumers treat non-`active` status as no-op.

## Cadence and safety defaults

`start` accepts optional `interval_s`, `timeout_s` (one renderer execution,
not the watch's whole lifetime), and `max_refreshes`. Omitted values use this
agent's configured defaults, persisted at `taskcard/taskcard.json`: `interval_s:
5`, `timeout_s: 10`, `max_refreshes: 2000`, unless an operator has configured
different values in that file.

`timeout_s` and `max_refreshes` are safety ceilings: an explicit value may
lower the configured ceiling but never exceed it — a request above the
ceiling is silently capped to it, it is not an error. `interval_s` has no
ceiling; only the absolute floor of 1 second applies, so requesting a slower
(larger) interval than the default is always honored — a numerically larger
interval is a safer, not a forbidden, choice.

Guidelines:

- Keep one active watch per agent. A second `start` is refused until the first
  watch is stopped.
- Write the body you want projected. The producer is channel-neutral and does
  not own Telegram/Feishu/portal layout details.
- Keep renderer output truthful and complete. Projection channels may compare
  file content byte-for-byte and update only on real changes. A channel that
  skips unchanged bytes still performs a real update whenever your renderer's
  output actually changes — choose `interval_s` and how often your renderer's
  output changes deliberately, since some consumer transports (e.g. Telegram)
  enforce their own message-edit/send rate limits on real changes.

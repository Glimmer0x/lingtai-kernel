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

Guidelines:

- Keep one active watch per agent. A second `start` is refused until the first
  watch is stopped.
- Write the body you want projected. The producer is channel-neutral and does
  not own Telegram/Feishu/portal layout details.
- Keep renderer output truthful and complete. Projection channels may compare
  file content byte-for-byte and update only on real changes.

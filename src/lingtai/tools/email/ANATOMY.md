---
related_files:
  - src/lingtai/__init__.py
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/email/CONTRACT.md
  - src/lingtai/tools/email/__init__.py
  - src/lingtai/tools/email/schema.py
  - src/lingtai/tools/email/manager.py
  - src/lingtai/tools/email/primitives.py
  - src/lingtai/tools/email/manual/SKILL.md
  - src/lingtai/tools/email/glossary-en.md
  - src/lingtai/tools/email/glossary-zh.md
  - src/lingtai/tools/email/glossary-wen.md
  - src/lingtai/tools/_settings.py
maintenance: |
  Keep this anatomy connected to src/lingtai/tools/ANATOMY.md and the email
  Contract. Describe ownership and data flow, not a second copy of the schema.
  Update it in the same change as implementation or public-contract edits.
---
# intrinsics/email

`email` is the filesystem mailbox intrinsic and the agent's internal
agent-to-agent communication channel. Its public boundary is the canonical
root `action` plus required closed nested `input` contract; its mailbox
semantics remain owned by the pre-existing manager/primitives split.

## Components

- `__init__.py` — public composition boundary. Registers the generic-dismiss
  guard, binds `EmailManager` in `boot`, reads fresh Agent-owned settings
  evidence, validates root/input mappings and value types without hashing
  untrusted keys, loads the installed manual, then flattens validated input
  only for the internal manager call. It appends `current_setting` to every
  result. It does not define a flat public alias or reimplement mailbox logic.
- `schema.py` — raw language-independent closed schema. It owns the exact
  action enum (`send`, `check`, `read`, `dismiss`, `reply`, `reply_all`,
  `search`, `archive`, `delete`, `contacts`, `add_contact`, `remove_contact`,
  `edit_contact`, `manual`) and one closed branch per action. It deliberately
  contains no root `reasoning` or executor-owned `summary` field.
- `manager.py` — `EmailManager`, the behavior owner. Its `handle` method and
  private action methods preserve send/check/read/dismiss/reply/reply_all/search/
  archive/delete/contact results, defaults, body limit, filter behavior,
  address modes, reply anchoring, duplicate-send guard, and errors.
- `primitives.py` — mailbox paths, JSON message/read tracking, delivery
  `_mailman`, display/filter helpers, and unread digest rendering. It remains
  an internal module; its flat dictionaries are not public tool input.
- `manual/SKILL.md` — installed read-only `email` manual. Its examples and
  guidance use `email(action=..., input={...})`; real internet email remains
  explicitly routed to IMAP/MCP.
- `glossary-en.md`, `glossary-zh.md`, `glossary-wen.md` — owner-local naming
  resources. Identifiers remain canonical English; localized bodies do not
  introduce aliases.

## Connections

`BaseAgent` imports and boots this intrinsic through its intrinsic registry.
`base_agent/tools.py` injects optional root `reasoning` into the provider-facing
copy of the raw schema and the tool inventory, while provider adapters retain
the nested schema in Chat, Responses, and Anthropic envelopes. The executor
strips `reasoning` before calling this dispatcher and may inject `_tc_id`; those
are runtime metadata, not email action fields.

`EmailManager._send` calls primitives for outbox/sent persistence and daemon
mailman dispatch. Incoming mail and read-state mutators route through
`primitives._rerender_unread_digest`, which publishes `.notification/email.json`
and the persistent notification projection. No public schema change alters
that notification or mail-service protocol.

`__init__.py` calls `tools._settings.read_settings(agent, "email")` on every
public outcome. The exact Agent-owned `settings/email.json` file is a strict v1
no-op evidence source; it cannot select providers, behavior, addresses,
credentials, or mailbox paths. Only source/revision/hash and bounded generic
error metadata reach `current_setting`.

## Data flow

```text
provider tool call
  -> BaseAgent root reasoning injection / executor metadata stripping
  -> email.__init__.handle (fresh settings read + closed validation)
  -> email manual OR EmailManager.handle(flat internal dispatch)
  -> current_setting copied onto result
  -> ToolExecutor/provider result envelope
```

For ordinary mailbox operations:

```text
send -> outbox + sent -> per-recipient _mailman -> mailbox/inbox
read/dismiss/archive/delete -> mailbox/read.json + unread digest rerender
reply/reply_all -> original record -> resolved peer/abs return route -> send
check/search -> mailbox folder reads -> established summaries/results
contacts -> mailbox/contacts.json atomic contact-book persistence
manual -> .library/intrinsic/capabilities/email/SKILL.md read only
```

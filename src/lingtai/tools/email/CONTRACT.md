---
name: email-contract
tool: email
contract_version: 2
related_files:
  - src/lingtai/tools/email/__init__.py
  - src/lingtai/tools/email/schema.py
  - src/lingtai/tools/email/manager.py
  - src/lingtai/tools/email/primitives.py
  - src/lingtai/tools/email/manual/SKILL.md
  - src/lingtai/tools/email/ANATOMY.md
  - src/lingtai/tools/_settings.py
maintenance: |
  Keep related_files as repo-relative paths to real files. The code is the
  behavior source; update this contract in the same change as breaking public
  action/input edits. The nested input contract is closed and has no flat
  compatibility aliases.
---

# Email capability contract

`email` is the internal LingTai filesystem mailbox. It is not internet email:
Gmail, Outlook, IMAP, SMTP, DNS, and external addresses belong to the `imap`
MCP addon. The public tool name and internal mailbox behavior remain unchanged.

## Public call boundary

Every public call has exactly this shape:

```python
email(action="<closed action>", input={<action-specific fields>}, reasoning="<optional root metadata>")
```

`action` and `input` are required. `input` is an object selected from the
closed action union below; every branch rejects extra keys. `reasoning` is
optional root metadata injected only by `BaseAgent`; it is not in the raw email
schema and is never nested in `input`. The tool does not advertise or own an
email `summary` field. There is no flat field alias, omitted-action default,
action healing, coercion, or `unread` public action.

The raw schema (`schema.py:get_schema`) contains only root `action` and
`input`, requires both, and sets root and branch `additionalProperties: false`.
Provider envelopes retain that nested schema (Responses may canonicalize
`oneOf` to its provider-compatible `anyOf`). The installed manual is a real
read-only `manual` action:

```python
email(action="manual", input={})
```

## Action surface and exact fields

All fields not listed for an action are rejected before mailbox, contact, or
transport dispatch. Optional fields are omitted rather than invented; the
manager's existing defaults apply.

| Action | Required input | Optional input and established defaults |
|---|---|---|
| `send` | `address` (string or list of strings), `message` (string) | `subject` string; `cc`, `bcc`, `attachments` (string arrays); `delay` integer default `0`; `mode` enum `peer`/`abs`, default `peer`; `type` enum `normal`, default `normal` |
| `check` | none | `folder` enum `inbox`/`sent`/`archive`, default `inbox`; `n` integer default `10` (non-positive means all); `filter` closed object with `sort` (`newest`/`oldest`, default `newest`), `from`, `subject`, `contains`, `after`, `before` strings, `unread_only`, `has_attachments` booleans, and `truncate` integer default `500` (non-positive keeps the full preview) |
| `read` | `email_id` (string or list of strings) | `folder` enum `inbox`/`sent`/`archive` |
| `dismiss` | `email_id` (string or list of strings) | none |
| `reply` | `email_id`, `message` (strings; `email_id` also accepts a string list and uses its first item) | `subject`, `cc`, `bcc` |
| `reply_all` | `email_id`, `message` | `subject`, `cc`, `bcc` |
| `search` | `query` string (case-insensitive regex) | `folder` enum `inbox`/`sent`/`archive`; omitted searches `inbox` and `sent` (the foundation implementation does not include archive by default) |
| `archive` | `email_id` (string or list) | none |
| `delete` | `email_id` (string or list) | `folder` enum `inbox`/`archive`, default `inbox`; `sent` is read-only |
| `contacts` | none | none |
| `add_contact` | `address` string, `name` string | `note` string |
| `remove_contact` | `address` string | none |
| `edit_contact` | `address` string | `name` and/or `note` strings |
| `manual` | none | none; reads only installed `email-manual/SKILL.md` |

Address `peer` resolves a bare agent name in the current `.lingtai` network;
`abs` treats the address as an absolute working-directory path and embeds a
return route. `cc` and `bcc` are recipient arrays; BCC is retained only in the
sender's sent record. Attachments are path strings passed through unchanged.
The 50,000-character internal body limit is enforced at send time. Duplicate
identical sends are blocked after the established guard threshold.

## Results and errors

The manager's established success/error payloads are preserved behind the
canonical dispatcher:

- `send` returns `{status: "sent", to, cc, bcc, delay}`; oversize returns
  `error`, `limit_chars`, and `actual_chars`; duplicate loops return
  `{status: "blocked", warning}`.
- `check` returns `{status: "ok", total, showing, emails}` and may add
  `truncated_by_budget`.
- `read` returns `{status: "ok", emails}` and may add `not_found` and `hint`;
  inbox records are marked read.
- `dismiss` returns `{status: "ok", dismissed}` and may add
  `already_handled`, `not_found`, and `hint`, without returning bodies.
- `reply`/`reply_all` return the established send result, preserving reply
  subject, anchoring, abs return-route, recipient, CC, and BCC behavior.
- `search` returns `{status: "ok", total, emails}`; missing query and invalid
  regex keep the established error messages.
- `archive` returns `{status: "ok", archived}` and optional `not_found`/`hint`.
- `delete` returns `{status: "ok", deleted}` and optional `not_found`/`hint`;
  deleting `sent` returns the established folder error.
- Contacts retain their established `added`/`updated`/`removed` and not-found
  result shapes.

Canonical envelope/type errors are returned before any mailbox or contact seam.
Every success, canonical validation error, manager error, and manual/degraded
result carries a fresh `current_setting` snapshot from the Agent-owned
`settings/email.json`. This snapshot is diagnostic-only and behavior-neutral:
missing is normal, `{"schema_version": 1}` is the only valid file, and unknown,
secret, duplicate, malformed, unstable, oversized, symlink, and non-regular
settings never select behavior or leak content. The snapshot exposes only
bounded source/revision/hash metadata, a no-op marker, a generic change hint,
and a bounded settings error when applicable.

## State and routing ownership

The manager remains the sole mailbox behavior owner. Paths are relative to the
Agent working directory:

```text
mailbox/inbox/<uuid>/message.json
mailbox/sent/<uuid>/message.json
mailbox/archive/<uuid>/message.json
mailbox/read.json
mailbox/contacts.json
.notification/email.json
```

`read`, `dismiss`, `archive`, and inbox `delete` preserve the existing read-state
and unread-digest rerender behavior. `send` writes one sent record and starts
one daemon `_mailman` delivery thread per recipient. `reply` and `reply_all`
resolve `_return_route`, absolute sender paths, or peer addresses exactly as
before; `reply_all` excludes self and the primary reply target from its CC fanout.
The public dispatcher flattens only after validation to call the internal
`EmailManager`; that internal implementation detail is not a second public
schema.

## Ownership boundary

- `schema.py` owns canonical identifiers and action-specific JSON Schema.
- `__init__.py` owns strict envelope validation, settings evidence, manual
  loading, and dispatch; it does not reimplement mailbox semantics.
- `manager.py` and `primitives.py` own established mailbox, delivery, reply,
  filter, archive/delete, contact, and notification behavior.
- `manual/SKILL.md`, `ANATOMY.md`, and the three owned glossaries teach the same
  nested public form. Real IMAP/MCP prose is intentionally not rewritten as
  internal `email` guidance.

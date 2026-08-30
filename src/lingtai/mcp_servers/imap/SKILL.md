---
name: imap-mcp-manual
description: |
  Progressive-disclosure usage manual for the IMAP/SMTP email MCP tool. Read this
  when you need detail beyond the one-line action descriptions: send vs reply,
  check/read/search over folders, the compound email_id (account:folder:uid),
  attachments, move/flag/delete/folders, contacts/accounts basics, and the
  important external-email side-effect caveats (real outbound mail — confirm
  before sending). Pulled on demand via action='manual'; you do not need to call
  it before every send.
version: 1.2.0
last_changed_at: 2026-08-29T00:00:00Z
related_files:
- src/lingtai/mcp_servers/imap/manager.py
- src/lingtai/mcp_servers/imap/server.py
- src/lingtai/mcp_servers/imap/service.py
- src/lingtai/mcp_servers/imap/_family.py
- src/lingtai/mcp_servers/imap/plugin.py
- src/lingtai/mcp_servers/imap/settings.py
- tests/test_imap_settings.py
maintenance: |
  Tracks the MCP server's manager/config/settings behavior; update when the server's setup or API surface changes.
---

# IMAP/SMTP email MCP — usage manual (progressive disclosure)

Pulled on demand via `action='manual'`; read it for detail beyond the tool
schema's one-line action descriptions.

## ACTIONS

| Action | Purpose | Arguments |
|---|---|---|
| `send` | compose a new email | `address`, `message`; optional `subject`, `cc`, `bcc`, `attachments` |
| `reply` | reply to an existing email; preserves threading/subject from the original | `email_id`, `message`; optional `cc`, `attachments` |
| `check` | list recent envelopes from a folder | optional `folder`, `n` |
| `read` | fetch full email(s) | `email_id` |
| `search` | server-side IMAP search | `query`; optional `folder` |
| `folders` | list available IMAP folders | — |
| `move` | move email(s) to another folder | `email_id`, `folder` (destination) |
| `flag` | set/clear flags | `email_id`, `flags` |
| `delete` | delete email(s) | `email_id` |
| `contacts` | list all contacts | — |
| `add_contact` | add/update a contact | `address`, `name`; optional `note` |
| `edit_contact` | update contact fields | `address`; optional `name`, `note` |
| `remove_contact` | remove a contact | `address` |
| `accounts` | list configured IMAP accounts and connection status | — |
| `settings` | show the bounded five-field owner settings inventory | empty object only |

`address`/`cc`/`bcc` accept a single string or a list; `email_id` takes one id or
a list of ids.

## IDS, FOLDERS, ACCOUNTS

- `email_id` is a compound key: `account:folder:uid` (e.g.
  `me@example.com:INBOX:1234`). Use the ids returned by `check`/`search`; do not
  construct them by hand. Every action response includes `account` set to the
  explicitly requested or default-resolved account, while returned compound ids
  retain their own account prefix.
- An empty or whitespace-only `folder` (check/search) or `account` (any action)
  is treated as omitted: `folder` defaults to `INBOX`, and `account` uses the
  default/sole account rather than failing with `Unknown account`. Most actions
  accept an optional `account` (email address), defaulting to the primary
  account. `move` is the exception — its destination `folder` is required, must
  be non-empty, and is never defaulted to `INBOX`.
- `flags` is required for `flag` and maps flag name to bool, e.g.
  `flags={"seen": true, "flagged": false}`; `flags={"seen": true}` marks read. A
  missing or empty `flags` returns an error rather than silently doing nothing.
- `search` queries use a server-side search DSL, e.g.
  `from:addr subject:text unseen since:YYYY-MM-DD`; supported fields depend on
  the IMAP addon, so prefer examples returned by this tool over raw RFC IMAP
  search syntax.

## READING & ATTACHMENTS

- You are encouraged to `read` multiple relevant — or even all unread — emails
  and think before acting.
- `attachments` is a list of file paths for `send`/`reply`. Relative paths
  resolve against the working dir; absolute paths must be inside it. Attach
  generated artifacts (charts, reports, CSVs, PDFs) as files rather than
  pasting a path into the body.

## SIDE EFFECTS & SAFETY

- `send` and `reply` deliver real email to real recipients over SMTP — this is an
  external, hard-to-undo side effect. Confirm the recipient list (including
  `cc`/`bcc`) and the body before sending unsolicited mail.
- When replying to external addresses, follow the caller's standing reply
  policy. Unknown external senders require explicit guidance, or confirmation
  that the sender is the same human who contacted you through an internal
  channel, before sending a real reply.
- `delete` and `move` change server-side mailbox state; double-check the
  `email_id`/`folder` before running them.
- Actions return a result dict on success or one carrying an `'error'` key on
  failure (e.g. unknown account, bad `email_id`, unreadable attachment). Check
  for the error and surface or act on it rather than assuming delivery.

## SETTINGS AND CONFIGURATION OWNERSHIP

`settings(input={})` is read-only progressive disclosure. It returns only
`key`, `current`, `default`, `configurable`, and the exact section pointer in
`comment`; it has no set, reset, or mutation API. All six IMAP rows are
sensitive, so both `current` and `default` render as `<redacted>`. Each SHOW
reads the running manager's complete ordered account snapshot and the exact
config reference that manager successfully loaded at startup. It never rereads
the config file or ambient environment and never reports prospective edits as
active. If that applied snapshot is unavailable or incoherent, the whole action
returns fixed `SETTINGS_UNAVAILABLE` with no rows or exception detail.

Every row is `configurable: true` because an authorized deployment owner can
use the existing launcher/private-file procedure described below. After an
authorized edit, relaunch the IMAP MCP and run a second SHOW to verify it.
`LINGTAI_AGENT_DIR` and `LINGTAI_MCP_NAME` are launcher-injected workdir/process
identity, not IMAP preferences and not additional settings.

Configuration loading is intentionally weak beyond strict JSON and the outer
account shape: it does not eagerly validate most value types, non-emptiness,
uniqueness, endpoint ranges, or OAuth keys. A value can therefore construct a
manager and still fail later when a connection or login uses it. SHOW reports
the constructed manager snapshot; it does not certify provider connectivity or
silently tighten startup validation.

### Config reference

`config_reference` is the sensitive JSON authority path resolved from
`LINGTAI_IMAP_CONFIG` for this running manager. `~` expands; a relative path
resolves under launcher-injected `LINGTAI_AGENT_DIR` or the process cwd. The
environment reference is the only source and there is no meaningful default.
Missing, unreadable, or invalid JSON prevents manager construction, so SHOW is
wholly unavailable. An authorized deployment owner stops the MCP, changes the
launcher's environment reference or its private JSON document, relaunches the
MCP, then verifies with a second SHOW.

### Account addresses

`account_addresses` is the complete ordered list of mailbox identities retained
by the running manager. Values originate in every `accounts[].email_address`
entry, or the legacy top-level `email_address` shape; there is no lower-
precedence source or meaningful default. The loader requires the key where an
account is constructed but does not otherwise validate its type, non-emptiness,
or uniqueness. An authorized owner stops the MCP, edits the private JSON
account list, relaunches it, then verifies with a second SHOW.

### Credentials

`credentials` reports one applied credential mode per account: OAuth,
password, or unconfigured. IMAP uses a truthy `accounts[].auth` value when
present and otherwise `accounts[].email_password`; SMTP always uses
`email_password`. There is no usable credential default. The loader does not
validate these values eagerly: a truthy non-object or incomplete OAuth value can
make SHOW unavailable or fail login, and unsupported OAuth type fails when IMAP
connects. An authorized owner stops the MCP, updates only the private JSON and
any externally enrolled token cache, relaunches it, then verifies with a second
SHOW. SHOW never returns credential content.

### IMAP endpoints

`imap_endpoints` is the ordered `host:port` list retained for mailbox reads and
IDLE. Each account may supply `imap_host` and `imap_port`; omitted fields fall
back independently to `imap.gmail.com` and `993`, making the meaningful default
endpoint `imap.gmail.com:993`. Account JSON has precedence. The loader does not
enforce host type or port type/range before construction; unusable values fail
when the IMAP client connects. An authorized owner stops the MCP, edits those
private JSON fields, relaunches it, then verifies with a second SHOW.

### SMTP endpoints

`smtp_endpoints` is the ordered `host:port` list retained for outbound mail.
Each account may supply `smtp_host` and `smtp_port`; omitted fields fall back
independently to `smtp.gmail.com` and `587`, making the meaningful default
endpoint `smtp.gmail.com:587`. Account JSON has precedence. The loader does not
enforce host type or port type/range before construction; unusable values fail
when SMTP is opened. An authorized owner stops the MCP, edits those private JSON
fields, relaunches it, then verifies with a second SHOW.

### OAuth configuration

`oauth_configuration` reports, per account, whether OAuth type, public client
id, and token-cache path are configured. Its source is `accounts[].auth`; the
meaningful default is no OAuth object. The implemented form uses type
`microsoft_oauth2`, string `client_id`, and a local `token_cache` path, but the
loader does not validate that object or its required keys before manager
construction. Login rejects unsupported or incomplete forms. An authorized
owner completes enrollment outside LingTai, stops the MCP, places the cache at
the private configured path, updates `auth`, relaunches the MCP, then verifies
with a second SHOW. SHOW never returns OAuth metadata or paths.

### Legacy fields are not settings

Two accepted fields have no runtime application seam and are not projected as
settings: `allowed_senders` is stored but never enforced, and `poll_interval`
defaults to `30` but is not read by the IMAP IDLE listener. Do not rely on
`allowed_senders` as an authorization boundary or claim that changing either
field affects a running or relaunched listener.

## PUBLIC TOOL FAMILY: strict LTP-v2

Raw MCP discovery exposes exactly one public tool, `imap`, as a strict LTP-v2
family with the closed root `{action, input, reasoning, summarize?}` (`action`,
`input`, and `reasoning` required) and a closed action-owned input branch.
`imap` actions are exactly `send`, `check`, `read`, `reply`, `search`, `delete`,
`move`, `flag`, `folders`, `contacts`, `add_contact`, `remove_contact`,
`edit_contact`, `accounts`, `settings`, and `manual`. `settings` is inserted
immediately before `manual`. For example, checking the default account's inbox
is `imap(action="check", input={}, reasoning="...")`, and
sending mail is `imap(action="send", input={"address": "a@b.com", "message":
"hi"}, reasoning="...")`. Do not use the retired flat/legacy shape (top-level
`address`/`message`/`email_id`/... alongside `action`), `_reasoning`, aliases,
or a generic dispatcher.

### Outlook IMAP OAuth
```json
{
  "accounts": [
    {
      "email_address": "user@outlook.com",
      "email_password": "smtp-app-password-or-token",
      "imap_host": "outlook.office365.com",
      "auth": {"type": "microsoft_oauth2", "client_id": "PUBLIC_CLIENT_ID", "token_cache": "imap/outlook.cache"}
    }
  ]
}
```
Generate the serialized cache with a trusted external MSAL enrollment flow, then place it at `token_cache` while the MCP is stopped.

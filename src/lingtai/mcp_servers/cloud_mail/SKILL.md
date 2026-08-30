---
name: cloud-mail-mcp-manual
description: |
  Progressive-disclosure usage manual for the Cloud Mail REST email MCP tool.
  Read this when you need detail beyond the one-line action descriptions:
  check/search filters, the compound id (account:emailId) for read, send (needs
  user credentials), plain vs HTML bodies, accounts/add_user basics, redacted
  owner-only settings/startup diagnosis, and external-email side-effect
  caveats. Pulled on demand via action='manual'; you do not need to call it
  before every send. Calls use the strict LTP-v2
  action/input/reasoning/summarize envelope.
version: 1.2.0
last_changed_at: "2026-08-29T00:00:00Z"
related_files:
- src/lingtai/mcp_servers/cloud_mail/manager.py
- src/lingtai/mcp_servers/cloud_mail/_family.py
- src/lingtai/mcp_servers/cloud_mail/plugin.py
- src/lingtai/mcp_servers/cloud_mail/settings.py
- src/lingtai/mcp_servers/cloud_mail/server.py
- src/lingtai/mcp_servers/cloud_mail/client.py
maintenance: |
  Tracks the MCP server's manager/config/settings behavior; update when the
  server's setup, redaction policy, or API surface changes.
---

# Cloud Mail MCP — usage manual (progressive disclosure)

Inbound mail also arrives automatically in your inbox via per-account polling,
so you don't have to poll `check` yourself.

Setup, config file/schema, credential and auth model, and watermark state are
owned by the `mcp-manual` skill (`reference/curated-addons.md`, §Cloud Mail
setup). Read it before editing config; do not guess field names.

## HOW TO CALL IT — the envelope

`cloud_mail` is a single strict LTP-v2 tool family. Every call takes a closed
root `{action, input, reasoning, summarize?}` — `action`, `input`, and
`reasoning` are required; `summarize` is optional and never nested under
`input`. `input` is the strict argument object **for the selected action
only**; a key from another action's branch is rejected before anything is
read or sent. Actions are exactly `check`, `search`, `read`, `send`,
`accounts`, `add_user`, `settings`, `manual`. `settings` is inserted
immediately before `manual` by the curated-plugin opt-in contract. Do not use a
flat/legacy shape, `_reasoning`, aliases, or a generic dispatcher.

```python
cloud_mail(action="check", input={"limit": 10}, reasoning="check for new mail")
cloud_mail(action="read", input={"id": "cloudmail:1234"}, reasoning="read the request")
cloud_mail(action="send", input={"address": "user@example.com", "message": "done"},
           reasoning="report completion")
cloud_mail(action="settings", input={}, reasoning="inspect effective owner settings")
```

**`summarize` guidance for this family.** `check`, `search`, and `read` are
**bulky-result** actions — mailbox listings and full email bodies can be long,
so `summarize=true` is reasonable when you only need the gist. Leave it false
when you need exact email ids, addresses, or verbatim body text, because you
will act on those literally. `send`, `accounts`, `add_user`, and `settings` are
**short-result**: their results are small and meant to be read exactly, so
leave `summarize` false. Call `manual` itself with `summarize=false` so
procedure and constraints are not summarized away.

## EMAIL IDS

- `read` fetches the full content of one email by compound id
  `id='<account>:<emailId>'`, or by `account` plus a numeric `email_id`. Use the
  ids returned by `check`/`search`; do not construct them by hand.

## READING: check / search

- `check`: list recent inbound emails (optional `limit`, plus the same filters
  as search).
- `search`: filter the public email list by `to_email`, `send_email`,
  `send_name`, `subject`, `content`, `time_sort` (`asc`/`desc`), and paginate
  with `num`/`size`. Filters are LIKE matches.

## SEND

- `send` requires user credentials in config (it logs in, then posts to
  `/email/send`). Provide `address` (recipient or list), and a body via
  `message`/`text` (plain) and/or `html`/`content_html` (HTML). Optional
  `subject`, `name` (sender display name), `send_account_id` (override sender).
- Attachments are NOT supported in this first pass.

## ACCOUNTS / ADD_USER

- `accounts`: redacted per-account status (no tokens/passwords).
- `add_user`: create a Cloud Mail user (`email`, `password`; optional
  `role_name`). Admin operation — use deliberately.

## SETTINGS

`settings` is read-only progressive disclosure. It accepts exactly `input={}`
and returns exactly two rows, in order: `config_path`, then `accounts`. Every
successful row contains only `key`, `current`, `default`, `configurable`, and
`comment`; there is no set/reset or other mutation operation. Both rows are
sensitive, so both `current` and `default` render as `<redacted>`, while
`comment` points back to the exact sections below.

`configurable=true` means an authorized owner can use the existing File/Shell,
`init.json`, and curated-MCP lifecycle procedures described here and in
`mcp-manual`; it does not grant this SHOW action write authority. After an
authorized change, perform a full Cloud Mail relaunch and call
`cloud_mail(action="settings", input={}, reasoning="verify owner settings")`
again. Editing the document alone does not change the running manager.

If the successfully loaded config path or constructed manager is unavailable,
the provider raises and the whole action returns only
`{"status":"failed","error_code":"SETTINGS_UNAVAILABLE","message":"settings inventory is unavailable"}`.
No partial row, path, account detail, or startup exception is returned. The
strict `settings` action/input envelope is still checked first, and `manual`
remains available when startup failed.

### Config path

- **Meaning/current/default:** `config_path` is the exact resolved path whose
  JSON document was successfully loaded for the running manager. It is an
  applied startup snapshot, not a fresh environment reread. There is no
  meaningful default because Cloud Mail cannot start without an authored
  configuration reference.
- **Accepted values and resolution:** the canonical environment key is
  `LINGTAI_CLOUD_MAIL_CONFIG`. Supply a nonempty JSON-file path; `~` expands,
  an absolute path is used directly, and a relative path resolves against
  `LINGTAI_AGENT_DIR` or the process cwd.
- **Source/precedence/timing:** the curated launcher's
  `mcp.cloud_mail.env.LINGTAI_CLOUD_MAIL_CONFIG` value is the sole source, so
  there is no fallback precedence. The successful resolved path is captured at
  manager construction; a change applies only after a full Cloud Mail relaunch.
- **Sensitivity/authorization:** the row is fully redacted because even the
  path can reveal private local layout and selects a credential-bearing file.
  Only an authorized owner should change it.
- **Change procedure:** follow `mcp-manual` → `reference/curated-addons.md`
  “The four-step setup.” Use the existing File/Shell procedure to edit the
  `cloud_mail` activation's environment value in the agent's `init.json`; do
  not add command/args/type for a curated addon. Confirm the target is a private
  valid JSON file, fully relaunch Cloud Mail through the existing lifecycle
  procedure, then call the `settings` action again with empty input.

### Accounts document

- **Meaning/current/default:** `accounts` is the configuration document
  selected by `config_path`. Successful manager construction supplies only the
  opaque current marker `"configured"`; the provider never traverses, copies,
  counts, or stringifies account records. There is no meaningful default.
- **Source/precedence/timing:** the referenced owner document is the sole
  source, with no environment or built-in fallback. Its active value is the
  running manager's startup snapshot; any authorized edit takes effect only
  after a full Cloud Mail relaunch.
- **Accepted outer shape:** use canonical `{accounts: [...]}` with a nonempty
  list, or the retained flat single-account shape containing `base_url`. Each
  account requires `base_url`; alias falls back to `admin_email` and then
  `base_url`.
- **Accepted account values:** `poll_interval` is parsed as
  `float(value or 30)`; supply a positive finite value because the current
  parser does not reject non-positive or non-finite floats.
  `notify_existing` defaults false, but any supplied truthy value enables it,
  so use a JSON boolean rather than a nonempty string such as `"false"`.
  An absent/falsey `allowed_senders` permits all senders; when supplied, use a
  JSON string list. A truthy non-iterable fails startup, and a string is
  currently iterated by character, so do not substitute a scalar. Missing or
  unreadable paths, invalid JSON, an empty/invalid outer shape, a missing
  `base_url`, or an unconvertible poll interval prevents manager startup.
- **Sensitivity/authorization:** endpoints, account identities, credentials,
  sender authority, allowlists, polling policy, and initial-notification policy
  remain private and are never projected by `settings`. Both displayed values
  are fully redacted. Only an authorized owner should edit the document.
- **Change procedure:** use the existing File/Shell procedure to edit the
  private JSON file selected above, following `mcp-manual` →
  `reference/curated-addons.md` “Cloud Mail setup.” Keep real credentials out
  of reports and examples. Fully relaunch Cloud Mail, verify ordinary
  readiness, then call the `settings` action again with empty input.

`LINGTAI_AGENT_DIR` and `LINGTAI_MCP_NAME` are launcher identity rather than
Cloud Mail preferences. Watermark files are derived delivery state, and cached
public/JWT tokens are session material. None is a row and none is writable
through `settings`.

## SIDE EFFECTS & SAFETY

- `send` delivers real email to real recipients — an external, hard-to-undo side
  effect. Confirm the recipient(s) and body before sending unsolicited mail.
- `add_user` mutates the Cloud Mail deployment's user set; double-check before
  running it.
- Actions return `{'status': 'ok', ...}` on success or `{'status': 'error',
  'error': <message>}` on failure. Check the status and surface or act on errors
  rather than assuming delivery.

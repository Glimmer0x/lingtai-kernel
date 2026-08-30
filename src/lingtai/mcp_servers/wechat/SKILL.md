---
name: wechat-mcp-manual
description: |
  Progressive-disclosure usage manual for the WeChat MCP tool. Read this when you
  need detail beyond the one-line action descriptions: user_id targeting, send vs
  reply, check/read/search, media_path attachments (image/video/voice/file),
  contacts/accounts basics, read-only settings inventory and owner procedures,
  and external-delivery side-effect caveats. Pulled on demand via action='manual';
  you do not need to call it before every send.
version: 1.4.0
last_changed_at: "2026-08-29T00:00:00-07:00"
related_files:
- src/lingtai/mcp_servers/wechat/manager.py
- src/lingtai/mcp_servers/wechat/server.py
- src/lingtai/mcp_servers/wechat/_family.py
- src/lingtai/mcp_servers/wechat/plugin.py
- src/lingtai/mcp_servers/wechat/settings.py
- src/lingtai/mcp_servers/wechat/api.py
- ENVIRONMENT_VARIABLES.md
- tests/test_wechat_settings.py
maintenance: |
  Tracks the MCP server's manager/config behavior; update when the server's setup or API surface changes.
---

# WeChat MCP — usage manual (progressive disclosure)

## PUBLIC TOOL FAMILY: strict LTP-v2

Raw MCP discovery exposes exactly one public tool, `wechat`. It is an
independent strict LTP-v2 family with the closed root
`{action, input, reasoning, summarize?}` (`action`, `input`, and `reasoning`
required). `action` selects one of the 11 actions below; `input` is a closed,
action-owned object — only that action's own fields are accepted, and a field
from another action (or any top-level/host-only key) is rejected before any
WeChat I/O runs. `wechat` actions are exactly `send`, `check`, `read`,
`reply`, `search`, `contacts`, `add_contact`, `remove_contact`, `accounts`,
`settings`, and `manual`. `settings` is inserted immediately before `manual`;
the `manual` action is the discovery path for this document. Do
not use the retired flat/legacy shape (arguments at the top level alongside
`action`), `_reasoning`, aliases, or a generic dispatcher.

Example call:

```json
{
  "action": "send",
  "input": {"user_id": "wxid_abc123@im.wechat", "text": "hi"},
  "reasoning": "acknowledging the user's question"
}
```

`send`'s `text` and `media_path` are independent, combinable fields (at least
one is required, and both may be given together in one call — see MEDIA /
ATTACHMENTS below), not a mutually exclusive choice.

## SETTINGS: READ-ONLY INVENTORY

Call `settings` with an empty input to inspect the active manager's startup
snapshot:

```json
{
  "action": "settings",
  "input": {},
  "reasoning": "checking active WeChat configuration"
}
```

Success is only `{"settings":[...]}`. Every row has exactly `key`, `current`,
`default`, `configurable`, and `comment`; `comment` points to one exact section
below. SHOW has no set, reset, or other mutation input, and it does not reread
the environment, `config.json`, or `credentials.json`. A missing manager,
malformed row, non-JSON value, provider failure, or partial failure returns one
bounded no-row failure. Sensitive rows keep all five fields but render both
`current` and `default` as `<redacted>`.

`configurable: true` means the external owner procedure in the named section
can change the next manager construction; it never means SHOW can write. Apply
the documented restart, then call SHOW again to verify the new active snapshot.
Launcher-injected `LINGTAI_AGENT_DIR` and `LINGTAI_MCP_NAME` are composition,
not WeChat preference rows.

## setting-config-path

`config_path` is the sensitive exact `config.json` path successfully resolved
and loaded for this manager. It has no meaningful default. The canonical source
is the non-empty `LINGTAI_WECHAT_CONFIG` launcher value: `~` expands, absolute
paths are used directly, and relative paths prefer `LINGTAI_AGENT_DIR`, then
the legacy project root; when the agent directory is absent, relative paths use
the process cwd. The required sibling `credentials.json` is loaded from that
resolved directory. Missing or unreadable paths fail manager startup. To change
the path, update the existing WeChat MCP launch environment, restart the MCP,
and verify the redacted row with SHOW. The path is redacted because it reveals
private filesystem layout.

## setting-base-url

`base_url` is the sensitive endpoint captured by the active manager. A truthy
`credentials.json.base_url` wins; otherwise a present `config.json.base_url`
is used, with `https://ilinkai.weixin.qq.com` only when the config key is
absent. The startup loader does not add endpoint type or non-empty validation,
so an unusable authored value fails through ordinary downstream API behavior.
To change it, update `config.json.base_url`, rerun
`lingtai-wechat-bootstrap <config-directory>` when the credentials value must
also change, restart the MCP, and verify only the redacted row. Never paste a
private endpoint into chat, logs, issues, or PRs.

## setting-poll-interval

`poll_interval` is the public `float(...)` snapshot used between completed
listener polls. `config.json.poll_interval` is the only authored source and
the fallback is `1.0`. Startup accepts exactly what Python `float()` accepts;
non-numeric input fails startup, while zero, negative, and non-finite values are
not rejected by the current loader. Zero or negative values collapse the
intended pause. A non-finite active value cannot be encoded by strict SHOW JSON,
so the complete inventory is unavailable rather than emitting invalid JSON.
Author a positive finite value, restart the MCP, and verify with SHOW.

## setting-allowed-users

`allowed_users` is the sensitive effective inbound authorization set. Missing,
`null`, `[]`, or another falsy `config.json.allowed_users` value becomes
unrestricted access and has the meaningful default `null`. A truthy value is
passed to `set()` without additional schema validation, so operators should
author a JSON list of WeChat user-ID strings; malformed values may fail startup
or normalize unexpectedly. Edit the selected `config.json`, restart the MCP,
and verify only the redacted row. Keep identifiers private and review an
unrestricted value deliberately.

## setting-bot-token

`bot_token` is the required truthy bearer-token snapshot loaded from the
sibling `credentials.json`; it has no default. The existing QR-login procedure
writes it. To replace it, run `lingtai-wechat-bootstrap <config-directory>` (or
the documented headless `cli_login` flow), complete authorization, restart the
MCP, and verify only the redacted row. Never edit, print, paste, log, or commit
the token.

## setting-user-id

`user_id` is the required truthy account-identity snapshot from the sibling
`credentials.json`; it has no default. To change the authorized account, rerun
`lingtai-wechat-bootstrap <config-directory>` (or the documented headless
`cli_login` flow), complete authorization for the intended account, restart
the MCP, and verify only the redacted row. This identity is distinct from
recipient IDs passed to messaging actions.

## RECIPIENTS: user_id

- Messages target a WeChat user by `user_id` (e.g. `wxid_abc123@im.wechat`).
  `user_id` is the routing truth; aliases are convenience labels only. Use the
  `user_id` returned by `check`/`read`/`contacts` and do not invent one — when
  in doubt, especially for replies, take it from `read`/`check`.

## SEND vs REPLY

- `reply` (`message_id` from read results, `text`) threads your response to a
  specific incoming message; prefer it when answering a particular message.
- `send` (`user_id`, `text`) starts a fresh message; use it for unsolicited or
  standalone messages.

## MEDIA / ATTACHMENTS

- `send` with `media_path` attaches a file (absolute or relative to the agent
  working directory; paths outside it are rejected). Type is detected from
  the extension: `.jpg`/`.png` → image, `.mp4` → video, `.wav`/`.mp3` → voice,
  anything else → file.
- For charts, reports, and other artifacts the user should open intact, send them
  as a file/document rather than pasting a local path into the message text.
- `text` and `media_path` may be given together in one `send` call. They are
  delivered as **two separate WeChat messages** — the text first, then the
  media — not as a single captioned attachment. A missing `media_path` file
  is rejected before any text is sent, but a later upload/transport failure
  can still leave the text delivered without the media.

## INBOUND MEDIA / FILES

- Inbound media is rendered into message text as tags such as `[Image: path]`,
  `[Voice: "transcript" (audio: path)]`, `[File: name (path)]`, and
  `[Video: path]`. Use those paths as local artifacts, not as messages to paste
  back to the user.
- WeChat document downloads may be encrypted/cache placeholders rather than the
  real PDF/ZIP/etc. Before parsing a received file, validate its magic bytes
  (for example `%PDF-` for PDFs, `PK` for ZIP/DOCX). If the bytes do not match
  the claimed file type, ask the user to re-export with WeChat "Save As" or send
  a cloud/download link. This is an agent-side validation practice, not a
  guarantee from the MCP transport.
- Images and transcribed voice messages are usually more directly usable, but
  still verify file existence/readability before analysis.

## READING: check / read / search

- `check`: list recent conversations with unread counts; treat previews as
  hints, not complete context.
- `read`: read messages from one user (`user_id`; optional `limit`). The read
  view merges inbox and sent messages, which helps confirm whether you already
  replied.
- `search`: regex search over inbox messages (`query`; optional `user_id`). It is
  for locating inbound content, not proving that no sent reply exists.

## WAKE / REPLAY / DUPLICATE-REPLY DISCIPLINE

- Reply once per inbound `message_id`. Before sending after a refresh, molt, or
  worker-hang recovery, use `read` to reconcile the merged inbox+sent view and
  avoid duplicate replies.
- If a wake notification is based on a preview and an immediate `read`/`check`
  seems blocked by idle/sleep recovery, acknowledge from the preview if safe,
  then retry the producer read once the agent is active. Avoid tight polling
  loops.
- Some runtimes deduplicate upstream inbound replay by provider `message_id` and
  cursor checkpoints; if investigating inflated unread counts, confirm the
  runtime version/state before assuming the MCP lost messages.

## CONTACTS / ACCOUNTS

- `contacts`: list saved contacts.
- `add_contact`: save a contact alias (`user_id`, `alias`).
- `remove_contact`: remove a contact (`alias` or `user_id`).
- `accounts`: list configured WeChat accounts.

## SIDE EFFECTS & ERROR SURFACING

- `send` and `reply` deliver to real users — external side effects. Confirm
  recipient and content before sending unsolicited messages.
- A successful provider response requires an explicit integer `ret: 0`. The
  result then says `delivery_status: provider_accepted` and
  `delivery_confirmed: false`: iLink accepted the request, but recipient delivery
  is not proven. Do not automatically replay an accepted request.
- For text-plus-media partial outcomes, legacy `partial_delivery: true` is only a
  replay-compatibility flag that a recipient-visible side effect may have occurred;
  `partial_provider_acceptance` and `delivery_confirmed: false` carry the precise
  meaning.
- Actions return a result dict on success or `{'error': <message>}` on failure
  (e.g. missing `user_id`, unreadable `media_path`). Check for the `'error'` key
  and surface or act on it rather than assuming delivery.

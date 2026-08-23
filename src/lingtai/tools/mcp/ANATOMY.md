---
related_files:
  - src/lingtai/services/LICC_NOTIFICATION_CONTRACT.md
  - src/lingtai/ANATOMY.md
  - src/lingtai/tools/mcp/BEHAVIORS.md
  - src/lingtai/tools/mcp/__init__.py
  - src/lingtai/services/mcp_inbox.py
  - src/lingtai/services/mcp_licc.py
  - src/lingtai/tools/mcp/manual/SKILL.md
  - src/lingtai/tools/mcp/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/ANATOMY.md
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/__init__.py
  - src/lingtai/adapters/tool_plugin_host.py
  - tests/test_tool_plugin_declaration.py
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/tools/plugin/ANATOMY.md
  - src/lingtai/mcp_servers/ANATOMY.md
  - tests/test_mcp_capability.py
  - tests/test_mcp_inbox.py
  - tests/test_tool_family_mcp_migration_parity.py
  - src/lingtai/tools/mcp/glossary-en.md
  - src/lingtai/tools/mcp/glossary-zh.md
  - src/lingtai/tools/mcp/glossary-wen.md
  - ENVIRONMENT_VARIABLES.md
  - src/lingtai/tools/mcp/manual/reference/curated-addons.md
  - src/lingtai/tools/mcp/manual/reference/third-party-and-legacy.md
  - src/lingtai/tools/mcp/manual/reference/troubleshooting.md
  - src/lingtai/tools/mcp/manual/scripts/find_readme.py
  - src/lingtai/tools/ANATOMY.md
maintenance: |
  Keep related_files as repo-relative paths to real files. Include neighboring
  ANATOMY.md files so the anatomy graph stays connected rather than isolated;
  anatomy links must be bidirectional. If you create a new ANATOMY.md, copy this
  maintenance field. If you notice drift between this anatomy and the code,
  report it. See lingtai-dev-guide for details.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# lingtai/tools/mcp + lingtai/services/mcp_* (split)

MCP capability — per-agent registry of MCP (Model Context Protocol) servers.
Pure presentation: reads the registry from disk, validates records, and renders
it as XML into the system prompt. No tool writes; all registry mutations happen
via file operations from the agent (`write`, `edit`).

Also includes the **LICC v1 (LingTai Inbox Callback Contract)** — a
filesystem-based inbox that lets out-of-process MCP servers push events into
the agent's inbox.

The model-visible notification projection for LICC events is governed by `src/lingtai/services/LICC_NOTIFICATION_CONTRACT.md`; touching `src/lingtai/services/mcp_inbox.py`, `src/lingtai/services/mcp_licc.py`, or curated human-message producer metadata must re-check that contract.

## Components

- `mcp/__init__.py` — MCP tool surface (the tool slice, ~350 lines). One model-facing LTP v2 family: the public tool name stays `mcp` and the public actions stay `info`/`manual`, now carried in the canonical `action` + `input` + `reasoning` + `summarize` envelope composed by the generic `lingtai.tools.tool_family` infrastructure (`src/lingtai/tools/tool_family/ANATOMY.md`). `get_description` (`src/lingtai/tools/mcp/__init__.py:219`), `get_schema` (`src/lingtai/tools/mcp/__init__.py:223`) returns `ToolFamily.build_schema()` with the pre-migration signpost `action` description preserved verbatim, `_build_family` (`src/lingtai/tools/mcp/__init__.py:170`) is the single source of the two-child registry — called with `None` at import for the module-level schema-only family `_FAMILY` (`src/lingtai/tools/mcp/__init__.py:330`, built after the declaration it derives from), which fails loudly on a duplicate/reserved-name collision and never dispatches, and called with the granted `ToolPluginHost` from `_bind` (`src/lingtai/tools/mcp/__init__.py:233`) for the real dispatching family whose `manual` child comes straight from `tool_family.manual.build_manual_child`, handed only `host.workdir` and the manual destination read back out of `DECLARATION.manual`; both paths take their per-action `input` schemas from `DECLARATION` too — which holds the one `_EMPTY_INPUT` literal (`src/lingtai/tools/mcp/__init__.py:160`) re-exported from `tool_family.manual.MANUAL_INPUT_SCHEMA` — so the declared, advertised, and validated shapes cannot drift. `_reconcile` (`src/lingtai/tools/mcp/__init__.py:74`) backs the `info` child and reaches the live Agent body only through `host.workdir.path` and `host.prompt_section.write_protected_section`, `_flatten_manual_result` (`src/lingtai/tools/mcp/__init__.py:113`) is the Host-owned adapter that turns the manual child's canonical `content`/`structuredContent` result back into mcp's flat `mcp_manual` public shape strictly *after* dispatch (no double wrap), and `handle_mcp` (closed over inside `_bind`, `src/lingtai/tools/mcp/__init__.py:245`) owns mcp's exact pre-migration unknown-action envelope — including the missing-action empty-string default and unhashable `action` values (issue #513), routed by tuple membership against `child_names`, which compares by `==` and never hashes — before delegating to `ToolFamily.handle`. Both actions declare a strict-empty `input`, so any extra input field fails before the registry is re-read or the manual is loaded. The registry infra now lives in `src/lingtai/services/mcp_registry.py`: `validate_record` (`src/lingtai/services/mcp_registry.py:72`), `validate_registry_line` (`src/lingtai/services/mcp_registry.py:118`), `read_registry` (`src/lingtai/services/mcp_registry.py:139`), `read_identities` (`src/lingtai/services/mcp_registry.py:253`), `decompress_addons` (`src/lingtai/services/mcp_registry.py:316`), `_load_catalog` (`src/lingtai/services/mcp_registry.py:43`), `_build_registry_xml` (`src/lingtai/services/mcp_registry.py:419`). **Account-identity discovery** (`src/lingtai/services/mcp_registry.py:253`): `read_identities` reads each addon's non-secret identity document at `system/mcp_identities/<name>.json` (schema `lingtai.mcp.identity.v1`) and projects every account through the secret-safe allowlist `IDENTITY_SAFE_ACCOUNT_KEYS` (`src/lingtai/services/mcp_registry.py:211`) via `_project_account` (`src/lingtai/services/mcp_registry.py:242`). The tool-slice `_reconcile` attaches the projected identity to each `registered` entry (`_registered_entry`, `src/lingtai/tools/mcp/__init__.py:66`) and the registry XML builder renders it into the prompt XML (`_build_identity_xml`, `src/lingtai/services/mcp_registry.py:399`). The projection is an allowlist, not a passthrough — tokens/passwords/secrets/headers and any unrecognized field are dropped even if an on-disk identity file contains them, so the generic surface can never leak what a producer bug might persist. The prompt render further narrows to `_PROMPT_ACCOUNT_KEYS` (`src/lingtai/services/mcp_registry.py:394`), which excludes `last_verified_at`: that field, and the identity-level `<last_verified_at>` that used to precede the account list, are volatile re-verification timestamps that change on plain refresh and would otherwise break prompt-cache stability. `read_identities` and the `mcp(action="info")` diagnostic payload still surface `last_verified_at` — only the model-facing prompt XML omits it.
- `src/lingtai/services/mcp_inbox.py` — LICC v1 filesystem inbox poller (the **consumer** half). `validate_event` validates required `from`/`subject`/`body` fields; `_format_notification_summary` is **deprecated** legacy helper (retained for backward compat); `_extract_preview_meta` pulls optional IM/chat scalars (`conversation_ref`, `message_ref`, `platform`, and the additive per-update `event_id` used by the persistent lane for event-identity dedup/delivery) out of `event["metadata"]` when present as non-empty strings, each capped at `_PREVIEW_META_FIELD_CAP` (200 chars), and curated IM structured fields (`latest_incoming`, `recent_messages`, `referenced_messages` — the full reply target when it falls outside the last-20 window) after a bounded JSON-safe copy (a right-typed structured field that is unserializable or over the `_PREVIEW_STRUCTURED_META_JSON_CAP` is replaced by an explicit `licc_structured_omitted` marker carrying the reason and a read-action recovery hint, never silently dropped) — these feed the kernel builder for `_meta.agent_meta.notifications.persistent.mcp.<channel>` (currently Telegram, WeChat, Feishu, WhatsApp) and are then stripped from the model-visible ephemeral lane by the per-channel `meta_block.sanitize_*_notification_after_persistent` wrappers (move, not duplicate — Jason #6148); `_consume_event` returns `(wake, preview)` where `preview = {"from": sender, "subject": subject, "preview": body[:_PREVIEW_FIELD_CAP], "preview_truncated": bool, **extracted_meta}` — only the body snippet gets capped (sender/subject are bounded by upstream construction); `_dispatch_summary` publishes to `.notification/mcp.<mcp_name>.json` via `notifications.submit`, embedding full body snippets once in `data.previews` while keeping `instructions` to read/check guidance plus lightweight sender/subject/metadata routing context; `_scan_once` coalesces per MCP, threading the preview list through; `MCPInboxPoller` class drives the poll loop. Body snippet cap is `_PREVIEW_FIELD_CAP = 10000`. Defines the shared contract constants `LICC_VERSION` / `INBOX_DIRNAME` / `DEAD_DIRNAME` / `TMP_SUFFIX` / `EVENT_SUFFIX`.
- `src/lingtai/services/mcp_licc.py` — LICC v1 client (the **producer** half). One public function, `push_inbox_event(sender, subject, body, *, metadata=None, wake=True, received_at=None, agent_dir=None, mcp_name=None, event_id=None) -> bool`, that an out-of-process MCP imports to drop one event into `<agent_dir>/.mcp_inbox/<mcp_name>/<event_id>.json`. Lightweight by design — importing it starts no threads and re-exports the contract constants (`LICC_VERSION`, `INBOX_DIRNAME`, `TMP_SUFFIX`, `EVENT_SUFFIX`) straight from `src/lingtai/services/mcp_inbox.py` so producer and consumer never drift. `agent_dir`/`mcp_name` default to env vars `LINGTAI_AGENT_DIR`/`LINGTAI_MCP_NAME` (kernel-injected per MCP); explicit params override for tests/advanced callers. Writes atomically: serialize → `<event_id>.json.tmp` → `flush`+`os.fsync` → `os.replace` onto the final `.json` (the poller ignores `.tmp`, so half-writes are never observed). `event_id` defaults to a fresh `uuid4().hex` (guarantees per-call uniqueness); explicit `mcp_name`/`event_id` path components are validated before use. The payload is checked with `validate_event` before writing, so the canonical producer does not intentionally emit dead-letterable events. Best-effort/silent: missing/invalid target, unsafe path component, invalid payload, or filesystem/serialization error → `False` (never raises into the MCP), with a terse, content-free log that never echoes `body`/`subject`/`metadata`.
- **Declared host-plugin route** — `mcp` is one declared family slice under the kernel-owned declared host-plugin contract; the shared C target also reserves `email`, `file`, `context`, `notification`, `soul`, `vision`, `web`, `daemon`, `system`, and `task_card` without claiming those candidate slices have merged (`src/lingtai/kernel/tool_plugin/ANATOMY.md`, `src/lingtai/kernel/tool_plugin/CONTRACT.md`, LABTs TP001/TP002). `DECLARATION` (`src/lingtai/tools/mcp/__init__.py:308`) is a static `ToolPluginDeclaration` built at module import with no Agent in existence: `actions=("info",)` (the reserved `manual` is appended by the declaration, never declared), one strict-empty `input` schema per action, `manual="mcp"` naming the installed manual destination that `_build_family` reads back out of it (one literal, not two), and `requires=("workdir", "prompt_section")` — the two host ports this family actually consumes. `_bind` (`src/lingtai/tools/mcp/__init__.py:233`) composes the family and the `handle_mcp` wrapper and returns a `BoundToolPlugin` whose `activate` is the boot reconcile; it mounts nothing, and `ToolPluginDeclaration.bind` refuses it outright if the composed schema advertises an action inventory other than the declared `public_actions`. `setup` (`src/lingtai/tools/mcp/__init__.py:333`) is now only composition wiring: it calls `lingtai.adapters.tool_plugin_host.register_agent_tool_plugins`, which reserves the official `mcp` name, grants the two ports, binds, activates, and mounts — in that order, so a name conflict is refused before the live tool surface is touched. The recut changed no public behavior: same tool name, same `["info", "manual"]` enum, same strict-empty inputs, same result shapes including the tool-specific `mcp_manual` body key (`tests/test_tool_family_mcp_migration_parity.py`, `tests/test_mcp_capability.py`, `tests/test_tool_plugin_declaration.py`).
- `mcp/manual/` — skill documentation (`SKILL.md`) plus reference docs (`curated-addons.md`, `third-party-and-legacy.md`, `troubleshooting.md`) and scripts (`find_readme.py`).

## Public API

The `mcp` tool exposes two signpost actions, called through the LTP v2 envelope
`mcp(action=..., input={}, reasoning="...")` (both actions take a strict-empty
`input`; `summarize` is the optional root presentation control):

| Action | Description |
|--------|-------------|
| `info` | Re-read the MCP registry and return runtime health (registry contents, problems, registry path) without the manual body. Each `registered` entry may carry a non-secret `identity` block (account alias, provider username/id/display name, non-secret routing counts) read from `system/mcp_identities/<name>.json` when the addon has published one. |
| `manual` | Return the mcp-manual skill body on demand, with no registry read, rescan, or mutation. |

### LICC v1 Inbox Protocol

Two halves share one wire format:

- **Producer** (`src/lingtai/services/mcp_licc.py`) — an out-of-process MCP calls `push_inbox_event(...)` to atomically drop an event into the inbox. This is the canonical client-side entry point; MCPs should import it rather than hand-rolling the atomic write.
- **Consumer** (`src/lingtai/services/mcp_inbox.py`) — `MCPInboxPoller` sweeps the inbox at `POLL_INTERVAL`, validates each event with `validate_event`, coalesces a `.notification/mcp.<name>.json`, and deletes the file.

MCP servers push events via filesystem writes:
```
<agent_working_dir>/.mcp_inbox/<mcp_name>/<event_id>.json
```

```python
from lingtai.services.mcp_licc import push_inbox_event
push_inbox_event("alice", "new DM", "hey, are you around?")  # agent_dir/mcp_name from env
```

Schema (v1):
```json
{
  "licc_version": 1,
  "from": "human-readable sender (required)",
  "subject": "one-line summary (required, max 200 chars)",
  "body": "full message body (required)",
  "metadata": {},
  "wake": true,
  "received_at": "ISO 8601"
}
```

Atomic write: write to `<event_id>.json.tmp`, fsync, then rename. `push_inbox_event` does exactly this (`os.replace`) so the poller never observes a half-written file.

## Internal Module Layout

```
mcp/__init__.py
  ├── Catalog
  │   ├── _load_catalog()           — reads kernel-shipped mcp_catalog.json, cached
  │   ├── load_catalog()            — public deep-copy read; agent.py's curated launcher resolution uses this
  │   └── decompress_addons()       — boot-time: append catalog entries for addons not in registry
  │
  ├── Validation
  │   ├── validate_record()         — validates a single MCP registry record
  │   └── validate_registry_line()  — validates a single JSONL line
  │
  ├── Registry I/O
  │   ├── read_registry()           — reads mcp_registry.jsonl, returns (valid, problems)
  │   └── _append_record()          — appends a validated record as a JSONL line
  │
  ├── Account-identity discovery (read-only, secret-safe)
  │   ├── IDENTITY_SAFE_ACCOUNT_KEYS — allowlist of non-secret per-account keys
  │   ├── _project_account()        — projects one account dict to the allowlist
  │   └── read_identities()         — reads system/mcp_identities/*.json (lingtai.mcp.identity.v1)
  │
  ├── XML builder
  │   ├── _escape_xml()             — XML entity escaping
  │   ├── _build_identity_xml()     — renders a non-secret <identity> block per MCP
  │   └── _build_registry_xml()     — renders registry records as <registered_mcp> XML
  │
  ├── Reconciliation
  │   ├── _registered_entry()       — builds one registered entry, attaching identity when present
  │   └── _reconcile()              — reads registry + identities, renders into prompt, returns snapshot
  │
  └── Tool surface
      ├── get_description/schema()  — module-level
      └── setup()                   — registers mcp tool, runs initial _reconcile

src/lingtai/services/mcp_inbox.py
  ├── Validation
  │   └── validate_event()              — validates a parsed LICC event
  │
  ├── Dispatch (signal-only since issue #37, .notification/ since this fix)
  │   ├── _format_notification_summary()— DEPRECATED; retained for backward compat
  │   ├── _consume_event()              — per-event log + wake intent collector
  │   └── _dispatch_summary()           — publishes to .notification/mcp.<name>.json
  │
  ├── Dead-letter
  │   └── _dead_letter()                — moves invalid file to .dead/ with .error.json sidecar
  │
  ├── Scanner
  │   └── _scan_once()                  — sweep .mcp_inbox/<mcp_name>/*.json,
  │                                       consume each event, post one summary per MCP
  │
  └── Poller
      └── MCPInboxPoller                — daemon thread that polls at POLL_INTERVAL (0.5s)
          ├── start()                   — creates root dir, starts poll thread
          └── stop()                    — signals stop, joins thread

src/lingtai/services/mcp_licc.py  (client-side producer; mirrors src/lingtai/services/mcp_inbox.py's consumer)
  ├── Re-exports                        — LICC_VERSION / INBOX_DIRNAME / TMP_SUFFIX / EVENT_SUFFIX (from src/lingtai/services/mcp_inbox.py)
  └── push_inbox_event()                — resolve agent_dir/mcp_name (args or env) → build v1 payload
                                          → atomic .tmp + fsync + os.replace → True / False (no-op or OSError)
```

## Key Invariants

- **Registry is append-only JSONL:** One record per line. Duplicates by name are flagged as problems during read. Mutations (register, deregister, update) happen via agent-side file operations.
- **Name convention:** Lowercase, dash-separated, bounded length (`^[a-z][a-z0-9_-]{0,30}$`).
- **Transport validation:** `stdio` requires `command` + `args`; `http` requires `url`.
- **Addons decompression is idempotent:** Running `decompress_addons()` multiple times produces the same registry. Existing records are never modified.
- **`{python}` substitution:** Catalog entries support `{python}` placeholder in command args, resolved to `sys.executable` at decompression time.
- **LICC atomicity:** Events must be written to `.json.tmp` then renamed to `.json`. Half-written `.tmp` files are ignored by the scanner. `mcp_licc.push_inbox_event` is the canonical producer that performs this (`flush` + `os.fsync` + `os.replace`); MCPs should call it rather than re-implement the dance.
- **LICC client is best-effort, path-safe, and receiver-validating:** `push_inbox_event` never raises into the calling MCP. Missing agent dir / mcp name (neither arg nor env var set), invalid MCP names, unsafe explicit event IDs, or payload fields rejected by `validate_event` → `False` no-op; filesystem/serialization errors → `False`. Failure logs are terse and never echo `body`/`subject`/`metadata` (which may carry user content or secrets). Producer and consumer share the contract constants and validation because `src/lingtai/services/mcp_licc.py` imports them from `src/lingtai/services/mcp_inbox.py` — they cannot drift.
- **LICC dead-letter:** Invalid events (parse errors, missing fields, unknown version, dispatch failures) are moved to `.dead/` with a `.error.json` sidecar. Dead-letters are never auto-deleted.
- **LICC bounded work:** `MAX_EVENTS_PER_CYCLE = 100` per MCP per sweep prevents pathological backlog from blocking the poller.
- **LICC notification projection contract:** raw `.notification/mcp.<name>.json` previews are only the producer mirror; once a producer has a persistent context lane, model-visible `_meta.agent_meta.notifications.attention` must be reduced to a minimal identity hook and content must move to `_meta.agent_meta.notifications.persistent` (see `src/lingtai/services/LICC_NOTIFICATION_CONTRACT.md`).
- **LICC notification shape (post-#37 + previews):** The coalesced notification carries the MCP name, event count, plus a `previews` list — one entry per consumed event with `{"from": <sender>, "subject": <subject>, "preview": <body[:_PREVIEW_FIELD_CAP]>}` and, **when the event opts in via `metadata`**, optional IM/chat scalars `conversation_ref`, `message_ref`, `platform`, `event_id` (each capped at `_PREVIEW_META_FIELD_CAP = 200` chars) and bounded JSON-safe structured fields `recent_messages` / `latest_incoming` / `referenced_messages` (each capped at `_PREVIEW_STRUCTURED_META_JSON_CAP = 20000` JSON chars) that curated IM producers (Telegram, WeChat, Feishu, WhatsApp) attach to feed the kernel `_meta.agent_meta.notifications.persistent.mcp.<name>` lane. Only well-formed non-empty string metadata values are copied; non-string/empty/unknown keys are silently ignored, so legacy events without metadata produce the identical preview shape as before. The body snippet is hard-truncated at `_PREVIEW_FIELD_CAP` (10000 chars); `from` and `subject` pass through uncapped (sender bounded by upstream construction; subject already validated `<= 200` chars by `validate_event`). Full message **bodies** are still NOT inlined — those stay behind the `<mcp>(action="check"/"read")` tool result. The original issue #37 invariant (no body duplication → no agent re-processing loop) is preserved; previews exist purely to let the agent triage which MCPs/messages deserve a read call. Multiple events from the same MCP in one sweep are coalesced into a single summary; `wake` is the OR of all per-event `wake` flags. Preview list length is naturally bounded by `MAX_EVENTS_PER_CYCLE` (100).
- **LICC uses `.notification/` filesystem-as-protocol:** `_dispatch_summary` publishes via `notifications.submit` to `.notification/mcp.<mcp_name>.json` instead of posting to the legacy inbox queue. This unifies MCP events with all other notification producers (email, soul, system events) in the kernel's `_sync_notifications` wire injection path.
- **Pure presentation:** The capability never writes to the registry file. It only reads and renders.
- **Task Card ownership:** the public `task_card` family is intrinsic and no
  longer mounted from Telegram MCP. Telegram consumes the intrinsic
  `taskcard/` files directly as a read-only projector; the MCP capability has no
  hidden Task Card reverse route to preserve.
- **Automatic Task Card behavior broadcast (manager-owned):** `TelegramManager` mechanically tails the agent's `logs/events.jsonl`, skips every event whose exact type is not `tool_call`, keeps the bounded latest-N safe projection (`tool_name`, `tool_args.action`, redacted/capped `_reasoning`), and broadcasts the same automatic frame to every persisted resident Task Card target. Refresh/molt rebuild the ephemeral offset/window from the journal; there is no BaseAgent row batching, heartbeat, result correlation, elapsed/DONE synthesis, API-error row, or automatic reverse call. The detailed lifecycle, truncation/partial-line behavior, and tests are mapped in `src/lingtai/mcp_servers/ANATOMY.md`.
- **Generic ToolExecutor observers remain optional:** `on_pre_dispatch_hook` / result-hook plumbing is a best-effort extension seam, not current Task Card ownership. Task Card rendering now observes only persisted `tool_call` events, so provider failures and `tool_result` events are deliberately not reconstructed into the automatic card.

## Dependencies

- `yaml` (PyYAML) — used by the skills capability's frontmatter parser (imported transitively; not directly used here)
- `lingtai.kernel.i18n` — `t()` for localized strings (imported but the description is hardcoded English)
- `lingtai.kernel.notifications` — `submit` (as `publish_notification`) for `.notification/` dispatch (in `src/lingtai/services/mcp_inbox.py`)
- `lingtai.kernel.tool_plugin` — `ToolPluginDeclaration` / `BoundToolPlugin` (module-level import; `ToolPluginHost` is TYPE_CHECKING only)
- `lingtai.adapters.tool_plugin_host` — `register_agent_tool_plugins`, imported lazily inside `setup` (the `lingtai.tools → lingtai` back-edge rule)
- `lingtai.kernel.base_agent.BaseAgent` — agent type (TYPE_CHECKING only)
- `lingtai.mcp_catalog.json` — kernel-shipped MCP catalog file (read at runtime)
- `lingtai.services.mcp_inbox` — `src/lingtai/services/mcp_licc.py` imports the contract constants (`LICC_VERSION`, `INBOX_DIRNAME`, `TMP_SUFFIX`, `EVENT_SUFFIX`) from it; stdlib only otherwise (`json`, `os`, `uuid`, `datetime`, `pathlib`, `logging`)
- env: `LINGTAI_AGENT_DIR` / `LINGTAI_MCP_NAME` — kernel-injected per spawned MCP (see `lingtai.agent`); the default source for `push_inbox_event`'s target

## Composition

- **Parent:** `src/lingtai/tools/` (tool slice); infra siblings live in `src/lingtai/services/`.
- **Siblings:** `daemon/`, `avatar/`, `knowledge/` (private durable memory), `skills/` (skill catalog), `bash/`.
- **Manual:** `mcp/manual/SKILL.md` — registration contract and usage guide.
- **Declared contract:** `src/lingtai/kernel/tool_plugin/` owns the declaration shape, the host ports, the reserved official-name list, and the fail-fast registrar; `src/lingtai/adapters/tool_plugin_host.py` is the production adapter over the live Agent body.
- **Kernel hooks:** `setup()` is called during capability initialization; `decompress_addons()` is called by the Agent initializer before `setup`. `MCPInboxPoller.start()/stop()` are called by the agent lifecycle.

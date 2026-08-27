---
name: system-settings-inventory-reference
description: >
  Exact read-only System catch-all settings inventory: ownership, effective
  sources, defaults, accepted values, invalid behavior, redaction, timing,
  authorized change procedures, and explicit non-settings.
tags: [lingtai, system, settings, init, llm, environment, read-only]
version: 1.0.0
last_changed_at: "2026-08-28T00:00:00Z"
related_files:
  - ENVIRONMENT_VARIABLES.md
  - src/lingtai/adapters/posix/mail.py
  - src/lingtai/auth/codex.py
  - src/lingtai/auth/codex_pool.py
  - src/lingtai/cli.py
  - src/lingtai/init_reader.py
  - src/lingtai/init_schema.py
  - src/lingtai/kernel/config.py
  - src/lingtai/kernel/config_resolve.py
  - src/lingtai/llm/_register.py
  - src/lingtai/llm/openai/adapter.py
  - src/lingtai/llm/service.py
  - src/lingtai/tools/email/CONTRACT.md
  - src/lingtai/tools/system/ANATOMY.md
  - src/lingtai/tools/system/CONTRACT.md
  - src/lingtai/tools/system/settings.py
  - src/lingtai/intrinsic_skills/system-manual/SKILL.md
  - tests/test_system_declared_plugin.py
maintenance: |
  Keep this owner manual aligned with System's ordered SHOW inventory, the
  canonical init/environment readers, and the focused classification tests.
  Add no mutation API; when ownership or runtime resolution changes, update
  the System Anatomy/Contract pair and this procedure together.
---

# System settings inventory

This reference teaches the kernel-level catch-all behind
`system(action="settings", input={})`. System owns a genuine adjustable
LingTai setting only when no other concrete ToolPlugin owns it. SHOW returns
exactly `key`, `current`, `default`, `configurable`, and `comment`; it never
sets, resets, writes, refreshes, or mutates process environment. A row with
`configurable: true` says only that an authorized external procedure below
exists. It does not authorize the caller to perform that procedure.

SHOW resolves one complete fresh snapshot. A malformed/unreadable `init.json`,
active preset, prompt source file, System owner document, or risky-action gate
document makes the whole inventory unavailable—there are no partial rows and
no exception details. Sensitive rows replace both `current` and `default` with
`<redacted>` before JSON serialization.

## Root and manifest inputs

The canonical source is the real `init.json` reader: JSONC parse, active-preset
materialization, provider inheritance, schema validation, and path resolution.
No environment peers are invented for these fields. An active preset replaces
the authored `manifest.llm` block and lifts its `llm.context_limit` to effective
`manifest.context_limit`; SHOW reports that materialized truth. For prompt
pairs, an existing `*_file` body wins the inline value, while a missing file
falls back to inline. Derived `system/manifest.resolved.json` is never authority.

| Key | Default and accepted value | Invalid behavior | Redaction | Application timing |
|---|---|---|---|---|
| `env_file` | absent; UTF-8 dotenv path | Missing file loads nothing; an invalid `init.json` path value fails the canonical read | full | Boot or System refresh; editing the dotenv needs refresh |
| `venv_path` | absent, so launcher-managed resolution applies; venv-root path | An unusable configured root fails launcher validation | full | Full relaunch only |
| `base_prompt` / `base_prompt_file` | empty inline / absent path; strings | Wrong types fail init validation; unreadable present source makes SHOW unavailable | full prompt and path | Prompt reconstruction on refresh |
| `covenant` / `covenant_file` | no default; one string source is required | Missing pair or wrong type fails init validation; unreadable present source makes SHOW unavailable | full prompt and path | Prompt reconstruction on refresh |
| `comment` / `comment_file` | empty inline / absent path; strings | Wrong types fail init validation; unreadable present source makes SHOW unavailable | full prompt and path | Prompt reconstruction on refresh |
| `agent_name` | `null`; string or null boot seed | Wrong type fails init validation | none | Creation/full relaunch only; immutable for an existing identity, so `configurable` is false |
| `language` | `en`; string | Wrong type fails init validation | none | System refresh |
| `disable` | `[]`; list | Wrong type fails init validation; entries are interpreted by capability composition | none | Capability rebuild during System refresh |
| `context_limit` | effective conservative window `272000`; positive integer or null | Wrong type fails validation; null uses the conservative service window | none | LLM/session rebuild during System refresh |
| `snapshot_interval` | `null` (off); positive finite number or null | Bool, zero, negative, or wrong type fails validation | none | Lifecycle rebuild during System refresh |
| `max_rpm` | `60`; integer, `0` disables the provider gate | Wrong type fails validation; the adapter applies only positive limits | none | LLM adapter rebuild during System refresh |
| `max_aed_attempts` | `3`; integer at least `1` | Bool, zero, negative, or wrong type fails validation | none | Recovery policy rebuild during System refresh |
| `aed_timeout` | `360.0`; positive finite number | Bool, zero, negative, non-finite, or wrong type fails validation | none | Recovery policy rebuild during System refresh |
| `admin` | `{}`; object | Wrong type fails validation | full authorization map | System refresh |
| `streaming` | `false`; boolean | Wrong type fails validation | none | Full relaunch; refresh does not rehydrate the session streaming flag |
| `time_awareness` | `true`; boolean | Wrong type fails validation | none | System refresh |
| `timezone_awareness` | `true`; boolean | Wrong type fails validation | none | System refresh |
| `preset.active` / `preset.default` | absent outside a preset block; non-empty strings and members of `allowed` | Missing/non-string/non-member values fail preset validation | full path/reference | Authorized preset workflow plus System refresh |
| `preset.allowed` | absent outside a preset block; non-empty `list[str]` when preset is present | Empty, non-list, or invalid entries fail preset validation | full path/reference list | Authorized preset workflow plus System refresh |
| `summarize_notification_threshold` | `3000`; non-negative integer, `0` disables the threshold hint | Negative or wrong type fails validation | none | System refresh |

`manifest.summarize_notification_threshold` remains System-owned: it controls
cross-cutting Agent/ToolExecutor result hints, not the Context ToolPlugin's
public summarize action. Conversely, `manifest.pseudo_agent_subscriptions`
belongs to the concrete Email ToolPlugin because CLI composition hands it
directly to `PosixFilesystemMailAdapter`, which resolves the subscription
paths. It is intentionally absent from System SHOW. A future Email-owner
classification and coverage change must add its owner-local discovery row and
fully redact both current and default path lists; this System repair does not
edit Email implementation.

Authorized change procedure: after explicit owner/human authorization, edit
the exact `init.json` field with the existing File or Shell capability. For a
preset-owned LLM/context value, edit the authorized preset outside SHOW or use
the existing `system(action="refresh", input={"preset": ...})` workflow; never
edit the derived resolved manifest or widen `preset.allowed` as a shortcut.
Run the refresh precheck, refresh/relaunch at the timing above, then call SHOW
again. For prompt/file pairs, changing or removing the pointer never changes
or deletes the referenced file. Existing identity changes use
`system(action="name_set"|"name_nickname")`; editing `manifest.agent_name` is
not a supported rename procedure.

## LLM and provider inputs

Every effective `manifest.llm` axis is System-owned because no LLM ToolPlugin
exists. Precedence is active preset over authored init for the whole block.
The credential path is the exception inside the materialized block: a named
non-empty `api_key_env` value wins inline `api_key`; when both resolve absent,
the service may use its provider-name API-key environment fallback. No secret,
alias value, header, auth path, endpoint pool, or credential-bearing URL is
ever projected.

| Key | Default and accepted value | Invalid behavior | Projection | Timing |
|---|---|---|---|---|
| `llm.provider` | no default; required string supported by the adapter registry | Missing/wrong type fails init; unknown provider fails adapter construction | literal | LLM rebuild on refresh |
| `llm.model` | no default; required string | Missing/wrong type fails init/provider construction | literal | LLM rebuild on refresh |
| `llm.api_key` | no universal default; string/null plus the credential precedence above | Missing required credentials fail provider use; alias misses use inline/fallback | `<redacted>` | LLM rebuild on refresh |
| `llm.api_key_env` | absent; environment-variable name | Wrong type, or alias without inline key and without `env_file`, fails canonical validation | `<redacted>` | Resolved at boot/refresh |
| `llm.base_url` | provider-owned when omitted; string/null | Provider validation owns unsupported endpoints | `<redacted>` because URLs may embed credentials | LLM rebuild on refresh |
| `llm.compact_threshold` | no universal owner default; positive integer or null. Official OpenAI and `_custom` names (`custom`, `grok`, `qwen`, `kimi`) with omitted or exact `openai` compatibility have selected-route default `100000`; omission consumes it and an explicit compact null disables only when that exact OpenAI route forwards the axis. Exact `anthropic`/`gemini` compatibility ignores it. Every other currently admitted compatibility value (including explicit compat null) falls through to `OpenAIAdapter` without forwarding this axis, so current/default are both `100000`. DeepSeek current is an authored positive value or null and default is null. Gemini/other ignored factories and native `codex`/`codex-pool`/`codex_pool` current/default are null; native Codex uses separate `codex_compact_token_limit` | Non-positive integer or wrong type fails validation | selected-adapter current and default | Adapter rebuild on refresh |
| `llm.wire_api` | `auto`; `auto`, `chat_completions`, or `responses` on its validated provider scope | Unknown value or unsupported provider/wire pairing fails init validation | literal | Adapter rebuild on refresh |
| `llm.inject_reasoning_fallback` | `true`; explicit boolean wins `LINGTAI_INJECT_REASONING_FALLBACK`, then on | Invalid environment form falls back on; wrong init type fails validation | literal | Adapter construction on refresh |
| `llm.reasoning_effort_vocab` | official OpenAI and `_custom` names (`custom`, `grok`, `qwen`, `kimi`) with omitted or exact `openai` compatibility have selected-route default `openai`; string/null (`seven_tier` selects retained alternate mapping), with omitted and explicit null consuming `openai`. Exact `anthropic`/`gemini` compatibility ignores the axis. Every other currently admitted compatibility value (including explicit compat null) falls through to `OpenAIAdapter` without forwarding the axis, so current/default remain `openai`. DeepSeek's provider policy, Gemini/other ignored factories, and all native Codex spellings ignore this generic axis, so current/default are null | Wrong type fails validation; other strings retain the OpenAI behavior only when the exact OpenAI route forwards them | selected-adapter current and default | Adapter rebuild on refresh |
| `llm.prompt_cache_namespace` | `null`; string/null | Wrong type fails validation | literal namespace only, never prompt/cache content | Adapter rebuild on refresh |
| `llm.service_tier` | absent; current runtime supports `fast` | Wrong type fails init; unsupported string fails adapter construction | literal | Adapter rebuild on refresh |
| `llm.thinking` | no static row default; omitted resolves to provider-owned `default` for Codex/DeepSeek and legacy `high` otherwise | Unsupported provider/model/wire or effort fails canonical/provider validation | literal effort only | Session rebuild on refresh |
| `llm.api_compat` | every name bound to `_custom` (`custom`, `grok`, `qwen`, `kimi`) has factory default `openai`; omitted and explicit null both select the OpenAI adapter branch, while the authored non-null value remains current and default stays `openai`. Exact `anthropic`/`gemini` select those adapters; every other currently admitted value falls through to OpenAI, but generic compact/reasoning axes are not forwarded because `_register._custom` forwards them only for exact lowercase `openai`. Official OpenAI, DeepSeek, Gemini/other ignored factories, and native `codex`/`codex-pool`/`codex_pool` ignore this axis, so current/default are null | No central type/value validator; the custom factory owns final exact-string/fallback selection behavior | selected-factory current and default | Adapter rebuild on refresh |
| `llm.codex_session_anchor` | derived from the resolved agent `init.json` path for Codex | Explicit value is an internal/testing escape, not an authorized production setting | `<redacted>` | Adapter rebuild; `configurable` is false |
| `llm.codex_auth_path` | provider-owned legacy auth path when absent; path-like override | Missing/unreadable/invalid auth fails the request/provider path closed | `<redacted>` | Adapter rebuild/request-owned reread |
| `llm.codex_auth_pool_path` | provider/TUI pool resolution when absent; path-like override | Invalid pool fails the provider account-source path closed | `<redacted>` | Adapter rebuild and request-bound account selection |
| `llm.codex_base_urls` | absent means single `base_url`; string or list accepted by the Codex adapter | Invalid/empty entries follow the adapter's pool validation/fallback | `<redacted>` | Adapter rebuild; selection rotates only at the documented molt boundary |
| `llm.default_headers` | `{}` user headers; JSON object in normal use | Non-object values are not forwarded as user headers; provider construction owns final validation | `<redacted>` including names and values | Adapter rebuild on refresh |

Authorized change procedure: after explicit owner/human authorization, update
the selected preset (when active) or `init.json`, keep credentials in the
supported private env/file source, run the refresh precheck, refresh, and SHOW
again. Never print a before/after credential, header, prompt, token, auth path,
or endpoint-pool value. SHOW never edits a preset, credential file, header map,
or process environment.

## Kernel environment controls

These are genuine kernel/LLM settings without another ToolPlugin owner. Direct
process-environment changes apply at the canonical read point; an `env_file`
edit first needs System refresh. Missing/invalid values fall back exactly as
shown. `LINGTAI_CODEX_WS` is a compatibility alias under the single
`llm.codex_transport` row: a non-empty canonical
`LINGTAI_CODEX_TRANSPORT` always decides first.

| Key (environment) | Default; accepted values; invalid behavior | Current read/application timing | Projection |
|---|---|---|---|
| `nudge.enabled` (`LINGTAI_NUDGE_ENABLED`) | on; `on/off`, `true/false`, `1/0`; invalid → on | Every Nudge operation | literal boolean |
| `nudge.repeat_interval_seconds` (`LINGTAI_NUDGE_REPEAT_INTERVAL`) | `86400`; positive duration with `s/m/h/d`; invalid → 24h | Every Nudge operation | numeric seconds |
| `nudge.folder_size_gb` (`LINGTAI_NUDGE_FOLDER_SIZE_GB`) | `5`; positive finite decimal GB; invalid → 5 | Every folder-size evaluation | number |
| `lifecycle.active_stuck_threshold_seconds` (`LINGTAI_ACTIVE_STUCK_THRESHOLD_S`) | `600`; numeric seconds floored to 30; parse failure → 600 | Each ACTIVE watchdog evaluation | number |
| `lifecycle.agent_alive_threshold_seconds` (`LINGTAI_AGENT_ALIVE_THRESHOLD_SEC`) | `10`; positive finite seconds; invalid → 10 | Kernel import/start (restart required); SHOW reports the imported effective constant | number |
| `prompt.tool_prose_section_enabled` (`LINGTAI_TOOL_PROSE_SECTION_ENABLED`) | off; `1/true/yes/on`; everything else off | Every prompt rebuild/provider payload | boolean |
| `prompt.system_prompt_pressure_ratio` (`LINGTAI_SYSTEM_PROMPT_PRESSURE_RATIO`) | `0.4`; finite `0 < value < 1`; invalid → 0.4 | Every metadata snapshot | number |
| `session_stats.refresh_seconds` (`LINGTAI_SESSION_STATS_REFRESH_SECONDS`) | `5`; positive finite seconds; invalid → 5 | Every Agent Record throttle check | number |
| `session_stats.daemon_limit` (`LINGTAI_SESSION_STATS_DAEMON_LIMIT`) | `1000`; positive integer; invalid → 1000 | Every Agent Record daemon aggregation | integer |
| `security.risky_action_gate` (`LINGTAI_RISKY_ACTION_GATE`) | off unless truthy env or `.security/gate_config.json` exists; `1/true/yes/on`; other env values off | Every gate-config load; malformed present document fails the guarded path and SHOW closed | enabled boolean only; never policy paths/lists |
| `logging.console_debug` (`LINGTAI_VERBOSE`) | off; exactly `1` enables boot DEBUG console logging; other values off | Agent boot/full relaunch | boolean |
| `llm.codex_tui_dir` (`LINGTAI_TUI_DIR`) | env path wins; when unset, `~/.lingtai-tui` is expanded with the current user home. Runtime accepts any path string and applies only `Path.expanduser` (relative paths remain relative; an explicit empty string denotes `.` rather than the default) | Codex adapter/account-source or default token-manager construction; change the launcher or `env_file` and fully relaunch before verification | `<redacted>` for both current and default |
| `llm.codex_transport` (`LINGTAI_CODEX_TRANSPORT`, alias `LINGTAI_CODEX_WS`) | REST; canonical `websocket/ws` or `rest/http/https`; alias truthy enables WS only when canonical is empty; invalid → REST | Adapter/session construction | literal `rest`/`websocket` |
| `llm.codex_ws_epoch_reset_turns` (`LINGTAI_CODEX_WS_EPOCH_RESET_TURNS`) | `0`; non-negative integer; invalid → 0 | Session construction | integer |
| `llm.codex_responses_trace` (`LINGTAI_CODEX_RESPONSES_TRACE`) | off; `1/true/yes/on`; other values off | Each trace-path decision | boolean |
| `llm.codex_responses_trace_path` (`LINGTAI_CODEX_RESPONSES_TRACE_PATH`) | trace default when enabled; local path | Each trace-path decision; unused while trace is off; write failure disables/fails the diagnostic path | `<redacted>` |
| `llm.read_timeout_seconds` (`LINGTAI_LLM_READ_TIMEOUT`) | `300`; positive finite seconds; invalid → 300 | Each OpenAI-compatible/Anthropic HTTP timeout build | number |

Authorized environment procedure: after explicit deployment-owner approval,
change the launcher environment or the agent's configured `env_file`; do not
mutate `os.environ` through a tool. Refresh when the source is `env_file`, and
restart only where the table says import/boot/session construction. Call SHOW
again and verify the effective value. Changing a threshold never grants access,
cleans files, resets counters, or authorizes a risky operation.

For `LINGTAI_TUI_DIR`, use that launcher procedure and a full relaunch. The
kernel does not create or validate the directory eagerly: an unexpandable `~`
can fail adapter construction, while a missing directory or unreadable/invalid
`codex-auth.json` / `codex-auth-pool.json` fails the later Codex account or
request path closed. Never print the resolved directory or credential paths;
SHOW fully redacts the env-selected and fallback paths.

## Explicit non-settings and exclusions

These classifications are tested against the canonical schemas/registry so
future fields cannot vanish silently:

- Concrete ToolPlugin owners stay out of System: Soul; Shell; Daemon;
  Notification; File/search sidecars; Vision; Web; Task Card; Plugin/Psyche;
  Skills; LingTai character; MCP, curated addons, and their config/session
  paths. `manifest.capabilities`, `manifest.plugins`, root `addons`/`mcp`, and
  root `lingtai`/`lingtai_file` therefore are not System rows.
- Inert/compatibility inputs are not settings: root `pad`/`pad_file` until its
  separate wiring decision, `manifest.activeness`,
  `manifest.llm.codex_thread_salt`, nested init
  `manifest.llm.context_limit`, `manifest.max_turns`, context-serialization
  template fields, retired molt/stamina fields, and retired prompt/soul fields.
- Kernel-fixed context-pressure thresholds, the hidden idle-sleep timeout, and
  fixed tool-loop safety limits are code policy rather than settings.

Do not infer product ownership from a registry source-path cell: the concrete
ToolPlugin rule and System catch-all rule above are authoritative.

### Concrete ToolPlugin environment exclusions

These registered production variables belong to concrete tools/integrations,
not System:

- `LINGTAI_CLAUDE_INTERACTIVE_FIFO`
- `LINGTAI_CLAUDE_MANAGED_ROOT`
- `LINGTAI_CLOUD_MAIL_CONFIG`
- `LINGTAI_DAEMON_SYSTEM_PROMPT_BUDGET_CHARS`
- `LINGTAI_FEISHU_CONFIG`
- `LINGTAI_FILE_IO_BACKEND`
- `LINGTAI_FILE_IO_SIDECAR`
- `LINGTAI_IMAP_CONFIG`
- `LINGTAI_NOTIFICATION_DELAY_MAX_SECONDS`
- `LINGTAI_NOTIFICATION_MAX_CHARS`
- `LINGTAI_SEARCH_SIDECAR`
- `LINGTAI_SHELL`
- `LINGTAI_SOUL_FLOW_ENABLED`
- `LINGTAI_TASKCARD_POLL_INTERVAL`
- `LINGTAI_TELEGRAM_CONFIG`
- `LINGTAI_TOOL_TIMEOUT_MAX_SECONDS`
- `LINGTAI_WECHAT_CONFIG`
- `LINGTAI_WHATSAPP_CONFIG`
- `LINGTAI_WHATSAPP_SESSION_DIR`

### Injected or handoff environment exclusions

These values describe one launcher/process edge, descriptor, or run identity,
not an adjustable kernel policy:

- `LINGTAI_AGENT_DIR`
- `LINGTAI_DAEMON_CAPSULE_FD`
- `LINGTAI_DAEMON_CAPSULE_HANDLE`
- `LINGTAI_DAEMON_COMPLETION_FILE`
- `LINGTAI_DAEMON_RUN_ID`
- `LINGTAI_MCP_NAME`
- `LINGTAI_REFRESH_ENV_OVERWRITE`
- `LINGTAI_RUNTIME_PYTHON`
- `LINGTAI_RUNTIME_VENV`

### Build-only environment exclusions

- `LINGTAI_REQUIRE_RUST_BUILD`
- `LINGTAI_SKIP_RUST_BUILD`

### Test-only environment exclusions

- `LINGTAI_DAEMON_SUPERVISOR_TEST_FAKE_LLM`
- `LINGTAI_DAEMON_SUPERVISOR_TEST_FAKE_LLM_FINISH`
- `LINGTAI_DAEMON_SUPERVISOR_TEST_FAKE_LLM_SCENARIO`
- `LINGTAI_DAEMON_SUPERVISOR_TEST_FAKE_LLM_SLEEP`
- `LINGTAI_FAKE_APP_SERVER_MODE`
- `LINGTAI_FAKE_CLI_REPORT`
- `LINGTAI_RUN_LIVE_KIMI_CODE`
- `LINGTAI_TEST_CONFIG`
- `LINGTAI_TEST_FAKE_CLAUDE_SIGNAL_RECORD`

### Unregistered concrete-owner baseline

The source census also finds four Daemon-owned production literals that are
absent from the current root environment registry. They remain explicit
concrete-owner exclusions here; this System change does not claim or document
them as System settings:

- `LINGTAI_DAEMON_MANAGER_POOL_SIZE`
- `LINGTAI_DAEMON_MANAGER_TOKEN`
- `LINGTAI_DAEMON_MEMORY_RELIEF`
- `LINGTAI_DAEMON_RUN_DIR`

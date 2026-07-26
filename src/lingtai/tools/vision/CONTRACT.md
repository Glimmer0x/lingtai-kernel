---
name: vision-contract
tool: vision
contract_version: 2
related_files:
  - src/lingtai/tools/vision/__init__.py
  - src/lingtai/tools/vision/ANATOMY.md
  - src/lingtai/tools/vision/manual/SKILL.md
maintenance: |
  Keep this contract aligned with the vision tool and its tests. Bump the
  version only for a repository-policy-required breaking contract change.
---
# Vision capability contract

`vision` analyzes one image through the active preset's current compatible route.
If direct setup is absent, unsupported, or fails, setup still registers the tool
and preserves a read-only `action="manual"` route. It never changes provider or
automatically invokes MCP.

## Public schema and registry

The raw tool schema is a closed object with exactly `action` and `input`, both
required. `action` is `analyze` or `manual`; `input` is an action-specific closed
object. The `analyze input` branch requires `image_path: string` and a required
nullable `question: string | null`; the `manual input` branch is exactly empty.
The strict nullable `question` representation allows providers to omit a
semantic optional value by sending `null`; the handler removes null (and accepts
direct-call omission) before applying the historical default
`Describe what you see in this image.`. `BaseAgent` adds only optional root
`reasoning` to the final Agent-facing schema; it is metadata, not nested input.

Canonical calls are:

```text
vision(action="analyze", input={"image_path": "photo.png", "question": null}, reasoning="inspect the image")
vision(action="manual", input={}, reasoning="load the read-only procedure")
```

Flat root `image_path`/`question`, action-only calls, unknown root keys, unknown
input keys, and mismatched action/input branches are rejected by the handler
before image/provider work. Manual works without an image and never starts a
backend, inspects settings for behavior, or invokes MCP. Relative image paths
resolve against the agent working directory.

`PROVIDERS["providers"]` is exactly: `gemini`, `anthropic`, `openai`,
`openrouter`, `custom`, `deepseek`, `minimax`, `mimo`, `glm`, `zhipu`, `grok`,
`qwen`, `kimi`, `codex`, `codex-pool`, `codex_pool`, `claude-code`, and
`claude_code`. The local mlx-vlm pseudo-provider remains available only through
explicit `add_capability(..., provider="local")` opt-in and is intentionally not
advertised to wizards/check-caps.

Claude Code is manual-only;
Codex aliases use native Codex Responses; MiniMax uses the Anthropic route.
OpenRouter and custom
deliberately try the current OpenAI-compatible model/endpoint/credential without
preflighting image support; other compatible aliases use the current
OpenAI/Anthropic identity. A real request failure is returned as a sanitized
vision tool error that points to `vision(action="manual", input={})` for explicit
alternatives, without silently switching model/provider or invoking MCP.

## Current identity and wires

Direct routes inherit identity only from the same current provider (including the
explicit GLM/Zhipu and codex-pool spelling pairs); a different provider must supply
its own model and credential. Missing identity fails closed to `manual` instead of
using a service default model, a default OAuth path, or an SDK environment key.
Codex provider spelling (`codex`, `codex-pool`, `codex_pool`) is only a
Codex-family compatibility gate: all three resolve to the one native Codex service,
and the spelling never selects the fixed/direct vs weighted/pool route. Within an
active Codex-family service, the route follows the active provider-default bucket
exactly as the canonical Codex factory does — it is the fixed/direct route iff the
active bucket carries a nonblank `codex_auth_path` (whose trimmed value is used as
the `token_path`), otherwise the weighted/pool route, which passes the exact pool-selected
credential reference (the selected candidate's token path) to the native Codex
vision service and never borrows the direct auth path. This holds regardless of the
requested spelling: an active `codex-pool`/`codex_pool` service that configures a
`codex_auth_path` is a direct route even when a pool path is also present, and an
active direct `codex` service stays direct even for an explicit `codex-pool`
request. Codex vision may inherit only the same active Codex-family service's model
and endpoint; a Codex request over an unrelated provider fails closed on the missing
current model without borrowing that provider's model, endpoint, or credential. When
no `base_url` is resolved, the native Codex service uses its existing official
default Codex endpoint (`https://chatgpt.com/backend-api/codex`) rather than failing
closed on base. A pool route that yields no selected candidate fails closed to
`manual` without manufacturing a direct or legacy-default identity.
OpenAI preserves current default headers, endpoint, model, and `wire_api`.
A missing, blank/whitespace-only, or `auto` selector means automatic selection:
the current route uses Responses only when it explicitly prefers Responses and
has no custom base URL; otherwise it uses Chat Completions. Unknown nonblank or
non-string selectors remain manual-only. Responses sends `max_output_tokens`.
MiniMax→Anthropic preserves active headers. MiMo accepts only API key/model/base
URL/max tokens: blank/auto resolves to its current Chat Completions route, which
constructs without headers/wire kwargs, while an active unsupported wire remains
manual-only.

## Tool behavior and settings evidence

Success is `{status: "ok", analysis: text, current_setting: {...}}`. Manual success
is `{status: "ok", action: "manual", manual: body, current_setting: {...}}`;
missing manual is degraded with the same diagnostic. Missing image, empty response,
setup failure, request failure, malformed/unknown input, and unknown action are
structured errors with `current_setting` and (where applicable) a pointer to
`vision(action="manual", input={})`. Exception messages are never returned; failures may
include only the provider and exception type.

Every handler call rereads `settings/vision.json` through the shared settings
reader before validation or behavior. Missing is normal; exact `{"schema_version": 1}`
is a valid metadata-only v1 snapshot. A valid snapshot is diagnostic-only and
cannot choose a provider/model/credential, enable a route, or alter defaults.
Malformed, unstable, non-regular, or oversized settings are reported as
`current_setting.source == "settings_error"` while existing behavior remains
unchanged. The revision/hash and source therefore prove hot rereads without
making the placeholder a configuration mechanism.

## Invariants and tests

- `setup` always registers the tool: `tests/test_vision_capability.py`.
- Endpoint identity is sanitized by `sanitize_endpoint` and drops userinfo,
  query, fragment, malformed ports, and non-URLs: `tests/test_agent_preset_manifest.py`.
- Provider construction and exact OpenAI Responses shape are covered in
  `tests/test_vision_capability.py`.
- Manual guidance is provider-neutral and kernel/TUI-independent in
  `manual/SKILL.md`.

Run `python -m pytest tests/test_vision_capability.py tests/test_vision_services.py -q`
and the glossary validator before merging.

---
name: vision-contract
tool: vision
contract_version: 1
related_files:
  - src/lingtai/tools/vision/__init__.py
  - src/lingtai/tools/vision/descriptor.py
  - src/lingtai/tools/vision/ANATOMY.md
  - src/lingtai/tools/vision/manual/SKILL.md
  - src/lingtai/tools/CONTRACT.md
  - src/lingtai/tools/tool_family/CONTRACT.md
maintenance: |
  Keep this contract aligned with the vision tool and its tests. Bump the
  version only for a repository-policy-required breaking contract change.
  vision's schema composition and envelope dispatch build on the generic
  tool_family package; keep that link current when either side's boundary
  changes.
---
# Vision capability contract

`vision` analyzes one image through the active preset's current compatible route.
If direct setup is absent, unsupported, or fails, setup still registers the tool
and preserves a read-only `action="manual"` route. It never changes provider or
automatically invokes MCP.

## Scope and registry
Guarded by: [VN001](BEHAVIORS.md#behavior-vn001)


`vision` is one action-separated family in the LingTai Tool Protocol v2 shape
defined in `src/lingtai/tools/CONTRACT.md`, built on the generic
`src/lingtai/tools/tool_family/` infrastructure (`ToolFamily`/`ChildTool` plus
the reusable ManualTool builder). The public tool name stays `vision` and its
public action values stay exactly `analyze`, `check`, `list`, and `manual`;
adopting the shared infrastructure changed no provider route, identity rule, or
result shape in this file. The package-local `descriptor.py`
`VISION_TOOL_DESCRIPTOR` is the one action/schema and installed-manual-name seam
consumed by both schema composition and manager binding. It owns no provider
selection, credential resolution, connectivity, or capability registration;
those remain in the host-facing manager/setup layer. Exactly one public
model-facing `vision` root is registered; its canonical children are not
separate tools and consume no model tool slots.

The model shape is the strict envelope `action` + `input` + `reasoning` +
optional `summarize`, with `required: [action, input, reasoning]` and
`additionalProperties: false`. The root exposes all four children' exact input
schemas before invocation (`input.oneOf`, one titled branch per action) and
correlates each `action` const with that child's own `input` at the root
(`allOf`/`if`/`then`), on both the Chat Completions and Responses wires.
`reasoning` is required Host InvocationContext/audit metadata and `summarize` is
Host presentation control; neither ever reaches child input. Child canonical
name equals public action value equals dispatch key — there is no mapping layer.

`analyze` owns a strict closed input of `image_path` (string) and `question`
(nullable string; null means absent and applies the unchanged default prompt
`Describe what you see in this image.`), both required as branch properties per
the strict-object convention. `manual` is the family-owned reserved child with
strict empty input. Analyze resolves relative `image_path` values against the
agent working directory. Unknown actions and invalid or cross-action `input`
fail at dispatch, before any handler runs and therefore before any provider I/O,
credential read, or image read.

`PROVIDERS["providers"]` is exactly: `gemini`, `anthropic`, `openai`,
`openrouter`, `custom`, `deepseek`, `minimax`, `mimo`, `glm`, `zhipu`, `grok`,
`qwen`, `kimi`, `codex`, `codex-pool`, `codex_pool`, `claude-p`, `claude-code`,
and `claude_code`. The local mlx-vlm pseudo-provider remains available only through
explicit `add_capability(..., provider="local")` opt-in and is intentionally not
advertised to wizards/check-caps. Claude Code returns explicit "use the Claude
CLI for vision" guidance (`claude -p "Analyze this image: <path>"` plus the
manual reference); Codex aliases use native Codex Responses; MiniMax uses the
Anthropic route. OpenRouter and custom
deliberately try the current OpenAI-compatible model/endpoint/credential without
preflighting image support; other compatible aliases use the current
OpenAI/Anthropic identity. A real request failure is returned as a sanitized
vision tool error that points to
`vision(action="manual", input={}, reasoning="...")` for explicit
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

## Tool behavior

Analyze success is exactly `{status: "ok", analysis: text}`. Manual success is
`{status: "ok", action: "manual", manual: body, manual_path: path}`, where
`body` is the full installed capability manual and `path` is its host-local
location; a missing installed manual is `degraded` with an empty body and the
loader's error. Manual performs no analyze operation, constructs no provider,
and reads no credential, even when the configured direct route is broken or
absent. The `manual` child's canonical result is adapted once by the Host into
that flat public shape after dispatch; it is never nested inside another action
result and is never double wrapped.

Missing image, empty response, setup failure, and request failure are structured
errors pointing to the full accepted envelope
`vision(action="manual", input={}, reasoning="...")` — every taught pointer
carries `input` and a contextual `reasoning`, because the bare shorthand is
rejected by the registered schema and the dispatcher. Envelope failures
(unknown action,
non-object `input`, unknown root field, non-boolean `summarize`, unknown or
cross-action `input` field) return the same `{status: "error", message: ...}`
shape. Exception messages are never returned; failures may include only the
provider and exception type.

## Invariants and tests

- `setup` always registers exactly one public `vision` tool:
  `tests/test_vision_capability.py`, `tests/test_tool_family_vision_migration.py`.
- Both child schemas and handlers, invalid/cross-action rejection before
  provider I/O, manual-without-provider-call, exact success/failure shapes, and
  Chat/Responses wire parity with no double wrap:
  `tests/test_tool_family_vision_migration.py`.
- The installed manual body/path round-trip alongside every other manual-owning
  tool: `tests/test_intrinsic_manual_actions.py`.
- Endpoint identity is sanitized by `sanitize_endpoint` and drops userinfo,
  query, fragment, malformed ports, and non-URLs: `tests/test_agent_preset_manifest.py`.
- Provider construction and exact OpenAI Responses shape are covered in
  `tests/test_vision_capability.py`.
- Manual guidance is provider-neutral and kernel/TUI-independent in
  `manual/SKILL.md`.

Run `python -m pytest tests/test_vision_capability.py tests/test_vision_services.py
tests/test_tool_family_vision_migration.py tests/test_intrinsic_manual_actions.py -q`
and the glossary validator before merging.

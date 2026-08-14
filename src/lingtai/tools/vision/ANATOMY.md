---
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/vision/BEHAVIORS.md
  - src/lingtai/tools/vision/__init__.py
  - src/lingtai/tools/vision/CONTRACT.md
  - src/lingtai/tools/vision/glossary-en.md
  - src/lingtai/tools/vision/glossary-zh.md
  - src/lingtai/tools/vision/glossary-wen.md
  - src/lingtai/tools/vision/manual/SKILL.md
  - src/lingtai/tools/tool_family/ANATOMY.md
  - src/lingtai/services/vision/ANATOMY.md
  - src/lingtai/tools/vision/settings.py
maintenance: |
  Keep related_files as repo-relative paths to real files and keep anatomy links
  reciprocal. Update citations with structural code changes and run the document
  validators after edits. tool_family is generic optional infrastructure this
  package composes onto; vision's own provider routing and result shapes stay
  here.
  Capability mentions in any document require explicit bidirectional
  related_files mapping to the implementing code (see root ## Maintenance).
---
# src/lingtai/tools/vision/

The `vision` tool registers one action-separated public family: direct
current-preset image analysis (`analyze`) plus a provider-neutral, family-owned
`manual` route when direct setup is unavailable. Schema composition and envelope
dispatch delegate to the generic `tool_family` infrastructure; this package
retains ownership of provider routing, identity resolution, and every action
result shape.

## Components

- `__init__.py:46-99` — Codex-family gate and bucket-driven route resolution plus the same-provider alias check; GLM/Zhipu and Codex spelling pairs share current identity, provider spelling is only a Codex-family compatibility gate, `_normalize_codex_auth_path` trims the bucket `codex_auth_path` once, and `_codex_bucket_route` picks direct (nonblank trimmed `codex_auth_path` in the active bucket) vs pool exactly as the canonical Codex factory does.
- `__init__.py:120-128` — exact advertised provider registry; the local pseudo-provider remains explicit opt-in and intentionally excluded.
- `__init__.py:130-150` — the two canonical child input schemas: `analyze` owns the strict `image_path`/nullable-`question` object, `manual` is strict empty.
- `__init__.py:152-199` — `_build_family`, the one canonical child declaration consumed by both the module-level schema-only family and every `VisionManager`, plus `get_description`/`get_schema`; the reserved `manual` child registers the generic `tool_family.manual.MANUAL_INPUT_SCHEMA` rather than a local copy, and the composed root exposes both exact child inputs and correlates each `action` const with its own `input`.
- `__init__.py:202-316` — `VisionManager`; builds its family through `_build_family` with the `analyze` handler bound to instance state and the reserved `manual` child from `tool_family.manual.build_manual_child`, `handle()` owns the canonical dispatch/presentation ordering and flattens the manual child's canonical result afterwards, `_dispatch_analyze` validates and reads the image.
- `__init__.py:319-614` — `setup`; resolves only the same current model/endpoint/credential/headers/wire, routes active Codex-family services by the bucket-driven direct (trimmed `codex_auth_path`) vs pool (pool-selected candidate token path) rule, creates supported services, fails closed to manual guidance when identity is incomplete, and always registers the one public `vision` tool.

- `settings.py` — strict per-Agent settings for the `provider: local` route. `settings/vision.json` is the family-owned provider configuration holding the operator-configured local OpenAI-compatible endpoint (`base_url`, `model`, optional `api_key`/`max_tokens`). It mirrors the `settings/web.json` pattern from `lingtai.tools.web_search.settings`: a bounded, race-checked read with a stable digest, so "default applied" is a truthful, verifiable fact (`src/lingtai/tools/vision/settings.py:1-8`).

## Connections

- Schema composition and envelope dispatch build on
  [`src/lingtai/tools/tool_family/ANATOMY.md`](../tool_family/ANATOMY.md), which
  knows nothing of vision's providers or identity rules.
- The reserved `manual` child reads the installed capability manual through the
  shared `_manual.py` loader, so `manual_path` is host-local and truthful.
- Setup lazily reaches `lingtai.services.vision` and the Codex pool selector.
- Direct compatible aliases (`openrouter`, `deepseek`, `zhipu`, `glm`, `grok`,
  `qwen`, `kimi`, `custom`) use current OpenAI/Anthropic-compatible identity.
- MiniMax uses Anthropic; Codex aliases use the Codex service; Claude Code
  (`claude-code`/`claude_code`/`claude-p`) returns explicit "use the Claude CLI
  for vision" guidance; unresolved/unsupported routes remain manual-only. No
  MCP fallback is used.

## Composition

`VisionManager` owns the agent, optional service, safe manual reason, and its
per-instance `ToolFamily`. The capability is registered by the built-in
capability loader and registers exactly one `vision` tool with the composed
schema and the glossary package.

## State

Only the in-memory manager/service/family references persist. Manual content is
bundled with the package and installed into the agent's intrinsic capability
library; analyses are not persisted.

## Notes

Setup failures retain provider plus exception type, never exception text. Direct
request failures likewise expose only the exception type and a manual pointer.
Active MiMo Responses/other unsupported wires are manual-only; supported Chat
Completions does not receive unsupported headers or wire kwargs.

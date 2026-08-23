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
  - src/lingtai/kernel/tool_plugin/ANATOMY.md
  - src/lingtai/adapters/tool_plugin_host.py
  - tests/test_tool_plugin_declaration.py
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
- `__init__.py` — `VisionConfiguration`, static `DECLARATION`, and the
  declaration-derived `_build_family` are one source for identity, action
  schemas, and the package-owned reserved manual. Import-time schema composition
  catches a malformed fixed family before an Agent exists.
- `__init__.py` — `_bind(host)` creates `VisionManager` from only the granted
  workdir/current-provider/configuration ports; it retains same-provider route,
  credential, Codex bucket, and local-settings behavior without retaining an
  Agent. `handle()` owns canonical dispatch/manual flattening.
- `__init__.py` — `setup` supplies the immutable public capability-kwargs
  snapshot to `register_agent_tool_plugins`; the kernel registrar is the sole
  mount path for the public `vision` name.

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

`VisionManager` owns only the granted workdir/current-provider ports, optional
service, safe manual reason, and its per-instance `ToolFamily`; it holds no
Agent. The built-in capability loader passes the setup configuration through
`register_agent_tool_plugins`, whose kernel registrar claims and mounts exactly
one `vision` tool with the declaration-derived schema and glossary package.

## State

Only the in-memory manager/service/family references persist. Manual content is
bundled with the package and installed into the agent's intrinsic capability
library; analyses are not persisted.

## Notes

Setup failures retain provider plus exception type, never exception text. Direct
request failures likewise expose only the exception type and a manual pointer.
Active MiMo Responses/other unsupported wires are manual-only; supported Chat
Completions does not receive unsupported headers or wire kwargs.

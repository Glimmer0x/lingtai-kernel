---
related_files:
  - src/lingtai/tools/ANATOMY.md
  - src/lingtai/tools/vision/BEHAVIORS.md
  - src/lingtai/tools/vision/__init__.py
  - src/lingtai/tools/vision/descriptor.py
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
current-preset image analysis (`analyze`), mechanical route discovery
(`check`/`list`), plus a provider-neutral, family-owned `manual` route when
direct setup is unavailable. Schema composition and envelope dispatch delegate
to the generic `tool_family` infrastructure; this package retains ownership of
provider routing, identity resolution, and every action result shape.

## Components

- `descriptor.py` — the package-local `VISION_TOOL_DESCRIPTOR`: the one ordered `analyze`/`check`/`list`/`manual` action inventory, strict input schemas, and vision-installed-manual name. It is pure composition: it does not select providers, resolve credentials, connect, or register a capability. It builds both the schema-only `ToolFamily` and each manager-bound family; with an agent it registers `build_manual_child(agent, "vision")` directly and verifies that the generic child still matches the descriptor's strict manual branch.
- `__init__.py` — provider aliases, current-route identity, service construction, and capability setup remain host-facing. `_FAMILY` is built from `VISION_TOOL_DESCRIPTOR` for `get_schema()`, while `VisionManager` binds only the analyze/check/list handlers through that same descriptor, then owns post-dispatch manual flattening and every provider result shape.

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

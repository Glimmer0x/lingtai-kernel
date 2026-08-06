---
related_files:
  - src/lingtai/llm/ANATOMY.md
  - src/lingtai/llm/opencode/__init__.py
  - src/lingtai/llm/opencode/adapter.py
  - src/lingtai/llm/opencode/defaults.py
  - src/lingtai/llm/openai/adapter.py
maintenance: |
  Keep related_files as repo-relative paths to real files. Include neighboring
  ANATOMY.md files so the anatomy graph stays connected rather than isolated;
  anatomy links must be bidirectional. If you create a new ANATOMY.md, copy this
  maintenance field. If you notice drift between this anatomy and the code,
  report it. See lingtai-dev-guide for details.
---
# src/lingtai/llm/opencode

OpenCode adapter — thin OpenAI-compat wrapper over the local `opencode serve` endpoint (`http://127.0.0.1:4050/v1`).

> **Maintenance:** see the `lingtai-kernel-anatomy` skill. **Coding agents** update this file in the same commit as code changes. **LingTai agents** report drift as issues.

## Components

| File | LOC | Role |
|------|-----|------|
| `__init__.py` | 4 | Re-exports `OpenCodeAdapter`, `DEFAULTS` |
| `adapter.py` | 62 | `OpenCodeAdapter(OpenAIAdapter)` — pinned to local serve endpoint |
| `defaults.py` | 6 | `DEFAULTS` dict: `api_compat=openai`, `base_url=http://127.0.0.1:4050/v1`, `api_key_env=""`, `model=""` |

### Classes

- **`OpenCodeAdapter(OpenAIAdapter)`** — default `base_url` is `http://127.0.0.1:4050/v1`; non-empty placeholder `api_key` satisfies the OpenAI SDK (opencode authenticates providers itself via `~/.local/share/opencode/auth.json`); Chat Completions wire by default (`wire_api="chat_completions"`), opt-in Responses via `wire_api`/`use_responses`; `prompt_cache_key` disabled by default (opencode has no shared prompt cache); overrides `_default_prompt_cache_key` → `lingtai-opencode:{model}:v1` for explicit opt-in.

## Connections

- **Inherits from**: `OpenAIAdapter` (`../openai/adapter.py`) — session management, tool calls, thinking-block replay, context-overflow auto-recovery.
- **Registered by**: `lingtai/llm/_register.py` `_opencode` factory under the provider name `opencode`.
- **Connectivity**: `lingtai/kernel/preset_connectivity.py` `_PROVIDER_DEFAULT_URLS["opencode"] = "http://127.0.0.1:4050"` — TCP probe of the local serve port.
- **Preset template**: `presets/templates/opencode.json` — mirrors the `codex.json` template shape with `provider: "opencode"`.

## State

Stateless adapter — no module-level mutable state.

## Notes

- **No API key**: `opencode serve` needs no LingTai-side credential; auth lives in the CLI (`opencode auth login`). The placeholder key is only for the OpenAI SDK constructor.
- **Model format**: `provider/model` (e.g. `anthropic/claude-sonnet-4-5`), resolved by the opencode server.
- **Not a THINKING_PROVIDER**: reasoning effort is opencode's per-provider `--variant` concept and is not mapped to `manifest.llm.thinking`; keep `thinking` out of the opencode preset template.
- **Capabilities**: tools only — opencode does not vend LingTai vision/web_search capability providers, so the template declares `skills` only (like `claude.json`).
- Git history: initial preset-provider PR.

---
name: opencode-preset-guide
description: >
  Reference for powering LingTai with OpenCode (github.com/sst/opencode) as a
  preset provider, the same way the codex sub preset works. OpenCode is a
  Go-based open-source coding agent CLI that runs locally, supports 75+ LLM
  providers through Models.dev, and serves an OpenAI-compatible API via
  `opencode serve` on http://127.0.0.1:4050 by default.
version: 1.0.0
tags: [preset, provider, opencode, llm]
last_changed_at: 2026-08-06T00:00:00Z
related_files:
- presets/templates/opencode.json
- src/lingtai/llm/opencode/adapter.py
- src/lingtai/llm/opencode/defaults.py
- src/lingtai/llm/_register.py
- src/lingtai/kernel/preset_connectivity.py
- src/lingtai/tools/bash/manual/reference/bash-opencode/SKILL.md
- src/lingtai/tools/daemon/manual/reference/cli-backends/reference/backends/opencode/SKILL.md
maintenance: |
  Tracks the OpenCode preset provider integration; update when the adapter,
  preset template, or connectivity entry changes.
---

# OpenCode as a LingTai Preset Provider

This page documents how to use OpenCode to power a LingTai agent as a **preset**
— the same pattern as the `codex` sub preset: a JSON preset template whose
`manifest.llm.provider` is `opencode`, wired to the local `opencode serve`
OpenAI-compatible endpoint instead of a hosted API.

## How it works

- `opencode serve` starts a headless HTTP server on `http://127.0.0.1:4050` by
  default, exposing OpenAI-compatible routes: `POST /v1/chat/completions`,
  `POST /v1/responses`, and `GET /v1/models`.
- Models are addressed as `provider/model` (for example
  `anthropic/claude-sonnet-4-5` or `openai/gpt-5.5`). The server resolves the
  provider prefix and authenticates through the CLI's own credential store
  (`~/.local/share/opencode/auth.json`, environment variables, or a project
  `.env`) — **no LingTai-side API key is needed**.
- LingTai's `opencode` provider is `OpenCodeAdapter`
  (`src/lingtai/llm/opencode/adapter.py`), a thin subclass of `OpenAIAdapter`
  pinned to `http://127.0.0.1:4050/v1`. It registers under the provider name
  `opencode` in `src/lingtai/llm/_register.py`.

## Prerequisites (on the machine running the agent)

```bash
# 1. Install OpenCode
curl -fsSL https://opencode.ai/install | bash
opencode --version

# 2. Authenticate at least one provider
opencode auth login          # interactive provider selection
opencode auth list

# 3. Start the headless server (default port 4050)
opencode serve
```

Run `opencode serve --port <port>` to change the port; then set the preset's
`base_url` to `http://127.0.0.1:<port>/v1`.

## Installing the preset

Copy the bundled template into the LingTai TUI preset templates directory:

```bash
cp presets/templates/opencode.json ~/.lingtai-tui/presets/templates/opencode.json
```

The template mirrors `codex.json`'s shape:

```json
{
  "name": "opencode",
  "description": {
    "summary": "OpenCode (local opencode serve) — any Models.dev provider, tool calls"
  },
  "manifest": {
    "capabilities": {
      "skills": {
        "paths": ["../.library_shared", "~/.lingtai-tui/utilities"]
      }
    },
    "llm": {
      "api_key": null,
      "api_key_env": "",
      "base_url": "http://127.0.0.1:4050/v1",
      "model": "anthropic/claude-sonnet-4-5",
      "provider": "opencode"
    }
  }
}
```

Key fields:

| Field | Value | Notes |
|---|---|---|
| `provider` | `opencode` | Registered adapter name (dash/underscore spellings are **not** aliased for opencode). |
| `base_url` | `http://127.0.0.1:4050/v1` | Must match the running `opencode serve` port. |
| `model` | any `provider/model` | Replace with a model from a provider you authenticated (`opencode models` lists the cache; `GET /v1/models` lists what the server exposes). |
| `api_key` / `api_key_env` | `null` / `""` | OpenCode owns its own auth; no LingTai credential. |

Then activate the preset (via the TUI, or by pointing `manifest.preset.active`
at the file). The agent's `manifest.llm` is substituted from the preset at
boot, exactly like the `codex` preset.

## Connectivity check

`preset_connectivity` probes the preset's LLM endpoint when listing presets:

- `_PROVIDER_DEFAULT_URLS["opencode"] = "http://127.0.0.1:4050"` — used when
  the preset omits `base_url`.
- With no `api_key_env`, the free credential check is skipped.
- The TCP probe succeeds only while `opencode serve` is actually running, so a
  stopped server shows `unreachable` — accurate, since the preset is unusable
  without it.

## What is (and is not) supported

- **Tool calls**: yes — the OpenAI-compatible Chat Completions wire is the
  default (`wire_api: "chat_completions"`); the Responses wire is available via
  `manifest.llm.wire_api: "responses"`.
- **Vision / web search capabilities**: not declared — opencode does not vend
  LingTai `vision`/`web_search` capability providers (unlike the codex preset
  whose capability providers are `codex`). The template declares `skills` only.
- **`manifest.llm.thinking`**: not supported for `opencode`. Reasoning effort in
  opencode is the per-provider `--variant` concept on the CLI, not a wire-level
  `reasoning.effort` contract LingTai can validate, so `opencode` is not in
  `THINKING_PROVIDERS` and the template omits `thinking`. An agent that needs
  explicit reasoning tiers should use the `codex` (or custom Responses) preset
  instead.
- **Multiple providers**: any provider you authenticate in opencode becomes
  selectable by changing `model` to `provider/model`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Preset shows `unreachable` | Start `opencode serve` (and check the port matches `base_url`). |
| `Connection refused` on first turn | The serve server is not running; opencode does not auto-spawn it from the adapter. |
| `No provider/model available` | `opencode auth login`, then `opencode models --refresh`. |
| Model not found | Pick a `provider/model` string the server exposes via `GET /v1/models`. |
| Wrong port | `opencode serve --port <port>` and set `base_url` to `http://127.0.0.1:<port>/v1`. |

See also the nested CLI references for OpenCode usage: the bash manual
`reference/bash-opencode/SKILL.md` and the daemon backend
`reference/cli-backends/reference/backends/opencode/SKILL.md`.

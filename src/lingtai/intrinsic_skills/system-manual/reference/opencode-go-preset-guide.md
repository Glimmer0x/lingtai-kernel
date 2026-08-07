---
name: opencode-go-preset-guide
description: >
  Reference for powering LingTai with the OpenCode Go subscription as a preset
  provider, the same way the codex sub preset works. OpenCode Go
  (https://opencode.ai/docs/go/) is a low-cost subscription ($5 first month,
  then $10/month) that gives reliable access to curated open coding models
  through a cloud OpenAI-compatible endpoint at
  https://opencode.ai/zen/go/v1.
version: 1.0.0
tags: [preset, provider, opencode, go, llm]
last_changed_at: 2026-08-07T00:00:00Z
related_files:
- presets/templates/opencode-go.json
- src/lingtai/kernel/preset_connectivity.py
- src/lingtai/llm/_register.py
- src/lingtai/intrinsic_skills/system-manual/reference/llm-adapters/SKILL.md
maintenance: |
  Tracks the OpenCode Go preset provider integration; update when the preset
  template or connectivity entry changes.
---

# OpenCode Go as a LingTai Preset Provider

This page documents how to power a LingTai agent with the **OpenCode Go
subscription** as a preset — the same pattern as the `codex` sub preset: a
JSON preset template whose `manifest.llm.provider` is `opencode-go`, pointing
straight at OpenCode's cloud Zen Go endpoint.

## How it works

- **OpenCode Go** is a subscription ($5 first month, then $10/month) for
  curated open coding models. It is separate from OpenCode Zen pay-as-you-go
  credits: the Go subscription carries its own usage allowance
  ($12/5h, $30/week, $60/month) and is billed by subscription, not balance.
- The **cloud endpoint** is `https://opencode.ai/zen/go/v1` (OpenAI-compatible):
  `POST /v1/chat/completions` for most models, `POST /v1/responses` for
  `gpt-5.6-luna`, `POST /v1/messages` for the MiniMax/Qwen models, and
  `GET /v1/models` for discovery.
- LingTai's `opencode-go` provider is **not a custom adapter**: it reuses the
  generic OpenAI-compatible adapter (`custom` factory) with
  `api_compat: "openai"` and `base_url` set to the Go endpoint. No local
  `opencode serve` process is needed.
- The model id in the LingTai preset is the bare Go model id (for example
  `glm-5.2` or `kimi-k3`). OpenCode's own config uses `opencode-go/<model-id>`
  for the same lane; LingTai sends the plain id to the endpoint.

## Prerequisites (on the machine running the agent)

```bash
# 1. Subscribe to OpenCode Go and copy your API key from the Zen console
#    (https://opencode.ai/auth)

# 2. Make the key available to the agent
#    Either set the env var the preset reads:
export OPENCODE_GO_API_KEY="sk-..."
#    or put the key in the preset's manifest.llm.api_key field directly.

# 3. Optional: verify the key works
curl -s https://opencode.ai/zen/go/v1/models \
  -H "Authorization: Bearer $OPENCODE_GO_API_KEY" | head
```

## Activating the preset

```bash
lingtai-agent preset activate ~/.lingtai-tui/presets/templates/opencode-go.json
```

or, in the TUI, pick **opencode-go** from the preset picker (it ships as a
built-in template). Then refresh the agent so the new LLM surface is live.

## Available Go models

The model list changes as OpenCode adds models. Fetch it live:

```bash
curl -s https://opencode.ai/zen/go/v1/models -H "Authorization: Bearer $OPENCODE_GO_API_KEY"
```

Known models (2026-08): `grok-4.5`, `gpt-5.6-luna`, `glm-5.2`, `glm-5.1`,
`kimi-k3`, `kimi-k2.7-code`, `kimi-k2.6`, `deepseek-v4-pro`,
`deepseek-v4-flash`, `minimax-m3`, `minimax-m2.7`, `minimax-m2.5`,
`qwen3.8-max`, `qwen3.7-max`, `qwen3.7-plus`, `qwen3.6-plus`, `mimo-v2.5`,
`hy3`, and more.

## Troubleshooting

- **`CreditsError: Insufficient balance` on `/zen/v1`** — that is the
  pay-as-you-go Zen lane. Use `/zen/go/v1` for the subscription lane, or add
  credits to the Zen balance if you meant pay-as-you-go.
- **`ModelError: Model X is not supported`** — X is not a Go model id. Fetch
  `/zen/go/v1/models` and use an id from that list.
- **`RegionError` for deepseek-v4-flash** — that model is only hosted in China
  and requires explicit opt-in at the workspace Go settings page.
- **Rate limits** — Go enforces `$12/5h`, `$30/week`, `$60/month` usage
  limits. If you also have Zen credits you can enable *Use balance* in the
  console so requests fall back to credits after the Go allowance is used.

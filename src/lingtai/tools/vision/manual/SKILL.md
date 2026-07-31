---
name: vision-manual
description: >
  Use this manual when the vision capability has no usable provider route or
  reports a direct setup/request failure and needs safe, provider-neutral
  troubleshooting guidance.
last_changed_at: 2026-07-27T00:00:00Z
related_files:
  - src/lingtai/tools/vision/__init__.py
  - src/lingtai/tools/vision/ANATOMY.md
  - src/lingtai/tools/vision/CONTRACT.md
maintenance: |
  Keep this manual provider-neutral and read-only. It must not import, name, or
  link to a TUI package, credential, endpoint secret, or automatic MCP action.
---
# Vision manual

This is the provider-neutral fallback for `vision`. It contains guidance only;
it does not discover, install, start, or invoke a backend.

## Call shape

`vision` is one action-separated tool with exactly two actions:

- `vision(action="analyze", input={"image_path": "...", "question": null},
  reasoning="...")` — the direct image request. `question` is optional: send
  `null` to use the default "Describe what you see in this image."
- `vision(action="manual", input={}, reasoning="...")` — this guidance. Its
  input is strictly empty and it performs no analyze operation.

`reasoning` is required on both actions and is recorded in your diary; it never
becomes part of the image request. Optional `summarize` is a root presentation
control, not action input. An unknown action, or an input field belonging to the
other action, is rejected before anything is sent to a provider.

## Route behavior and failures

For OpenRouter and custom OpenAI-compatible presets, `analyze` first tries the
current endpoint, model, and credential. It does not reject the route merely
because downstream image support cannot be known in advance. Any direct setup or
request failure returns a sanitized vision tool result that reports the failure
type and points here for explicit alternatives; it never exposes exception
contents.

## Stay on the active preset

Inspect the identity already shown in the prompt: the current provider, model,
and sanitized endpoint. Do not substitute another provider, model, credential,
endpoint, or wire protocol, and never silently switch or auto-invoke an MCP.
Retry only after the operator has corrected the active preset.

## Find the current preset's method

Use the `skills` capability's catalog to search your own installed skills for a
manual matching that provider/model or preset. Read the matching manual before
trying its documented method or official-page pointer. If no matching manual is
present, report that no discoverable vision method is available.

An optional MCP or other skill may be described by that preset manual, but it
is always an explicit operator/agent action. This manual never auto-loads or
auto-invokes MCP.

## Safety

Never request or print API keys, OAuth tokens, environment values, headers, or
full unsanitized URLs. Missing provider, model, or endpoint fields are simply
unknown; do not fill them with guesses.

## Local vision with Ollama (first-class provider)

`provider="ollama"` is a built-in local route: it needs no API key, defaults to
`http://localhost:11434/v1`, and uses a small vision model (`moondream`) unless
one is configured. It is the fastest way to get private, offline image
understanding on a machine that already runs Ollama.

### 1. Install and pull a vision model

Install [Ollama](https://ollama.com) for your platform, then pull a vision-capable
model. `moondream` is the recommended default: it is tiny (~1.7 GB), runs on
CPU or a small GPU, and is sufficient for OCR and basic image description.

    ollama pull moondream

Other vision-capable Ollama models exist (for example the `llava` family or
`qwen2.5vl`); pull whichever fits your hardware. The model must be a vision
model — a text-only model will fail at request time with a "does not support
images" style error.

### 2. Configure the capability

In `init.json` (or the active preset's `manifest.capabilities`), declare the
vision capability with provider `ollama`. Both of these work:

    "vision": {
      "provider": "ollama",
      "model": "moondream"
    }

    "vision": {
      "provider": "ollama",
      "model": "moondream",
      "base_url": "http://localhost:11434/v1",
      "max_tokens": 1024
    }

`model` must name a model you actually pulled. `base_url` defaults to
`http://localhost:11434/v1`; change it only when Ollama runs elsewhere or on a
non-default port (the `/v1` OpenAI-compatible suffix is required). `api_key` is
optional — Ollama ignores its value, so the kernel synthesizes a placeholder.

> **Preset note.** If your agent uses an active preset (a `manifest.preset`
> block), the preset's `manifest.capabilities` replace `init.json`'s for
> non-core opt-in capabilities like `vision`. Add the `vision` entry to the
> preset file (or the `default` preset) rather than only to `init.json`, then
> refresh.

### 3. Use it

After configuring and refreshing, the `vision` tool is available:

    vision(action="analyze", input={"image_path": "/path/to/image.png", "question": null}, reasoning="...")

A successful call returns `{"status": "ok", "analysis": "..."}`. If you get a
sanitized setup failure instead, check the troubleshooting table below.

### 4. Troubleshooting local Ollama vision

| Symptom | Likely cause / fix |
|---|---|
| "No direct vision provider was configured" | The `vision` capability is not in the effective manifest. Add it to the preset (see the preset note above), then refresh. |
| Connection refused on `localhost:11434` | Ollama is not running. Start it (`ollama serve` or the desktop app) and retry. |
| "model 'moondream' not found" | The model was never pulled or has a different name. Run `ollama list` and `ollama pull <name>`, then set `model` to the exact pulled name. |
| "does not support images" / vision request rejected | The configured model is text-only. Pull a vision model (e.g. `moondream`) and point `model` at it. |
| "...missing the '/v1' suffix..." (from the service) | `base_url` is missing the OpenAI-compatible suffix. Use `http://localhost:11434/v1`. |
| HTML/JSON parse failure on the response | Ollama returned a non-ChatCompletion body — usually the route is wrong (see previous row) or an old Ollama version. Upgrade Ollama and use `/v1`. |
| GPU not used / slow | Ollama offloads to the GPU only when the model fits VRAM. `moondream` fits most GPUs; larger models fall back to CPU. Use `ollama ps` to confirm. |

## Other local OpenAI-compatible servers

Any local server that speaks the OpenAI Chat Completions API with image support
(LM Studio, vLLM, llama.cpp server, etc.) can be wired through the generic
custom relay with an explicit OpenAI-compatible shape:

    "vision": {
      "provider": "custom",
      "api_compat": "openai",
      "model": "<vision-model-name>",
      "base_url": "http://localhost:1234/v1",
      "api_key": "local-placeholder"
    }

Unlike `ollama`, the generic custom relay still requires a non-blank `api_key`
string (many local servers accept any value); supply a placeholder. The manual
above stays provider-neutral: the concrete server name and port are operator
configuration, not something this manual auto-discovers.

---
name: vision-manual
description: >
  Use this manual when the vision capability has no usable provider route or
  reports a direct setup/request failure and needs safe, provider-neutral
  troubleshooting guidance.
last_changed_at: 2026-08-09T00:00:00Z
related_files:
  - src/lingtai/tools/vision/__init__.py
  - src/lingtai/tools/vision/ANATOMY.md
  - src/lingtai/tools/vision/CONTRACT.md
  - src/lingtai/kernel/tool_plugin/CONTRACT.md
maintenance: |
  Keep this manual provider-neutral and read-only. It must not import, name, or
  link to a TUI package, credential, endpoint secret, or automatic MCP action.
---
# Vision manual

This is the provider-neutral fallback for `vision`. It contains guidance only;
it does not discover, install, start, or invoke a backend. The static official
Vision declaration owns this package as its `manual="vision"` destination, so
the registrar-bound `manual` action reads this installed `SKILL.md` and not a
host-global or another family’s skill.

## Call shape

`vision` is one action-separated tool with these actions:

- `vision(action="analyze", input={"image_path": "...", "question": null},
  reasoning="...")` — the direct image request. `question` is optional: send
  `null` to use the default "Describe what you see in this image." The optional
  `preset` input field borrows another allowed preset's vision service for this
  one call (e.g. `"preset": "codex-pool"`); it must be a path listed in
  `manifest.preset.allowed`.
- `vision(action="check", input={"preset": null}, reasoning="...")` — resolve
  which vision route actually works without sending an image. With a `preset`
  value it borrows that preset's service and reports the resolved
  provider/model; with `null` it checks the default route. It constructs the
  service but never makes a provider call, so it costs nothing and cannot fail
  on image content.
- `vision(action="list", input={}, reasoning="...")` — mechanically enumerate
  the available vision routes without any provider call. It reports the default
  route (active provider/model, whether it supports vision, its endpoint
  classification, and whether it is a Responses-API vision model) plus every
  preset listed in `manifest.preset.allowed` that declares a vision capability
  (its provider/model, endpoint classification, and whether the model is valid
  for the Responses API vision endpoint). It never constructs a service or
  reads a credential.
- `vision(action="manual", input={}, reasoning="...")` — this guidance. Its
  input is strictly empty and it performs no analyze operation.

`reasoning` is required on every action and is recorded in your diary; it never
becomes part of the image request. Optional `summarize` is a root presentation
control, not action input. An unknown action, or an input field belonging to the
other action, is rejected before anything is sent to a provider.

## Route behavior and failures

`vision` is always registered. With no explicit `provider`, `analyze` defaults
its route to the active LLM's own Responses API (model, endpoint, and
credential inherited from the current provider). For OpenRouter and custom
OpenAI-compatible presets, `analyze` first tries the current endpoint, model,
and credential. It does not reject the route merely because downstream image
support cannot be known in advance. A call may instead borrow another allowed
preset's vision service with the `preset` input option; that preset must be
listed in `manifest.preset.allowed`, and its own provider/model/credential
identity (e.g. a `codex-pool` preset selecting its OAuth pool) is used for that
one call. Any direct setup or request failure returns a sanitized vision tool
result that reports the failure type and points here for explicit alternatives;
it never exposes exception contents.

### Borrow flow

To use another already-authorized preset's vision service for one image request:

1. Run `vision(action="list", input={}, reasoning="...")` first to see which
   allowed presets declare vision and which of those are Responses-API vision
   models.
2. Optionally run `vision(action="check", input={"preset": "<allowed preset>"},
   reasoning="...")` to resolve the borrowed route and its provider/model
   without sending an image.
3. Then run `vision(action="analyze",
   input={"image_path": "...", "preset": "<allowed preset>"},
   reasoning="...")` to send one image request through that preset's service.

The preset must be listed in `manifest.preset.allowed`; borrowing never
silently switches the active preset, reads another preset's secret, or
auto-invokes MCP.

## Claude backend: use the Claude CLI for vision

When the active provider is a Claude-family backend (`claude-code`, `claude_code`,
or the `claude-p` vision alias), the vision capability does not proxy Claude's
own CLI authentication. The analyze call fails closed with explicit guidance
instead of constructing a service:

> You are using claude as backend, therefore to use vision run `claude -p`;
> see the vision manual for more details.

### How Claude CLI vision works

Claude Code attaches images by file path: when the prompt references an image
path, the CLI reads the file and sends it to the model as an image input block
alongside the text. `-p` / `--print` is the non-interactive print mode, so the
analysis is returned as plain text on stdout — ideal for scripting.

- Run in print mode with the image path referenced in the prompt:
  `claude -p "Analyze this image: /path/to/image.png"`.
- Supported image formats include JPEG, PNG, and GIF (GIF uses the first
  frame). The CLI uses its own authentication (claude.ai subscription, API
  key, or a configured provider) and its own cost model.
- The CLI may also accept the image as a positional argument or via paste in
  interactive mode; print mode with the path in the prompt is the scriptable
  route.

### Progressive disclosure to the official docs

For the latest authoritative explanation of image input, supported formats,
output formats, and model support, progressively read the Claude Code CLI
documentation on the official website:

- CLI reference: <https://code.claude.com/docs/en/cli-reference>
- Image workflows: <https://code.claude.com/docs/en/common-workflows>

This manual never auto-invokes the CLI; running `claude -p` is an explicit
operator/agent action with the CLI's own auth and cost model.

## Stay on the active preset

Inspect the identity already shown in the prompt: the current provider, model,
and sanitized endpoint. The default route follows the active LLM; do not
substitute another provider, model, credential, endpoint, or wire protocol, and
never silently switch or auto-invoke an MCP. If the active route cannot see
images, the call fails explicitly; borrow another preset's vision service only
when it is already authorized in `manifest.preset.allowed`. Retry only after the
operator has corrected the active preset.

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

## Local vision (generic OpenAI-compatible provider)

`provider="local"` points the `vision` capability at any local
OpenAI-compatible vision server (Ollama, LM Studio, vLLM, llama.cpp server, ...)
by URL. It needs no API key (a placeholder is synthesized; local servers ignore
it), defaults `base_url` to `http://localhost:11434/v1`, and requires an
explicit `model` - there is no hidden default model, because a silently assumed
model masks misconfiguration.

The endpoint is operator-owned. Configure it in `settings/vision.json` (the
family-owned file, like `settings/web.json`), in the capability manifest, or
both (capability kwargs override the file).

### 1. Pick and install a server + pull a vision model

Any server that speaks the OpenAI Chat Completions API with image support
works. Examples:

- **Ollama** (easiest): install from <https://ollama.com>, then pull a
  vision-capable model. `moondream` is a good small default (~1.7 GB, runs on
  CPU or a small GPU, fine for OCR and basic description):

      ollama pull moondream

  Other vision-capable Ollama models exist (`llava`, `qwen2.5vl`, ...). The
  model must be a vision model - a text-only model fails at request time with a
  "does not support images" style error.

- **LM Studio**: start a local server with an image-capable model, note the
  port (default `http://localhost:1234/v1`).
- **vLLM / llama.cpp server**: serve a multimodal model and point `base_url` at
  its `/v1` endpoint.

### 2. Configure the endpoint

Two equivalent ways; capability kwargs win over the file.

**`settings/vision.json`** (agent working dir, applies on next refresh):

    {
      "schema_version": 1,
      "base_url": "http://localhost:11434/v1",
      "model": "moondream",
      "max_tokens": 1024
    }

`api_key` is optional and omitted here. Only `schema_version` plus the
documented fields are allowed; an invalid file is a hard setup error surfaced
as manual guidance.

**Capability manifest** (`init.json` or the active preset's
`manifest.capabilities`):

    "vision": {
      "provider": "local",
      "model": "moondream"
    }

    "vision": {
      "provider": "local",
      "model": "moondream",
      "base_url": "http://localhost:11434/v1",
      "max_tokens": 1024
    }

`model` is required and must name a model the server actually serves. `base_url`
defaults to `http://localhost:11434/v1`; change it when the server runs on a
non-default port (the `/v1` OpenAI-compatible suffix is required). `api_key` is
optional - local servers ignore it, so a placeholder is synthesized.

> **Preset note.** `vision` is always registered; an explicit `capabilities.vision`
> entry is **not** required to make the tool appear. The default route inherits
> the active LLM's own Responses API. A capability-manifest entry (in
> `init.json` or the active preset) is only needed to override that default,
> e.g. to point at `provider="local"`. To borrow another preset's vision
> service for a single call, list that preset in `manifest.preset.allowed` and
> pass `preset` on the analyze call; no `capabilities.vision` edit is needed.

### 3. Use it

After configuring and refreshing, the `vision` tool is available:

    vision(action="analyze", input={"image_path": "/path/to/image.png", "question": null}, reasoning="...")

A successful call returns `{"status": "ok", "analysis": "..."}`. If you get a
sanitized setup failure instead, check the troubleshooting table below.

### 4. Troubleshooting local vision

| Symptom | Likely cause / fix |
|---|---|
| "No direct vision provider was configured" | No explicit provider and no usable active-LLM route. The tool is always registered; either borrow an allowed preset's vision service via the `preset` option, or configure a local route (see below), then refresh. |
| "Local vision needs an explicit model" | No `model` is set in `settings/vision.json` or the capability manifest. Set `model` to a pulled/served vision model name, then refresh. |
| "Local vision settings are invalid" | `settings/vision.json` has an unknown field, bad type, or a schema_version other than 1. Fix the file and refresh. |
| Connection refused on the endpoint | The local server is not running. Start it (`ollama serve` or the desktop app) and retry. |
| "model '<name>' not found" | The model was never pulled or has a different name. Run `ollama list` (or your server's model list) and set `model` to the exact name. |
| "does not support images" / vision request rejected | The configured model is text-only. Pull/serve a vision model (e.g. `moondream`) and point `model` at it. |
| "...missing the '/v1' suffix..." (from the service) | `base_url` is missing the OpenAI-compatible suffix. Use e.g. `http://localhost:11434/v1`. |
| HTML/JSON parse failure on the response | The server returned a non-ChatCompletion body - usually the route is wrong (see previous row) or the server is too old. Upgrade and use `/v1`. |
| GPU not used / slow | The server offloads to the GPU only when the model fits VRAM. `moondream` fits most GPUs; larger models fall back to CPU. |

### 5. Apple MLX (macOS only)

The native on-device MLX pseudo-provider (`provider="mlx"`) is available as an
explicit opt-in for Apple Silicon. It is not advertised in check-caps; pass
`model` (an `mlx-community/...` vision model) and `max_tokens`. It requires no
API key.

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

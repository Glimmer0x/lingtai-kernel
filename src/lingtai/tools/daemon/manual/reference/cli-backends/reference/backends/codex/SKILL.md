---
name: daemon-backend-codex
description: >
  Nested daemon-cli-backends reference for the Codex daemon backend's flag
  surface. Read this when a daemon task needs Codex-specific CLI flags (model
  selection, reasoning effort, config overrides) or the operational core folded
  in from the retired bash reference guide: install, auth/config, and the
  Codex-vs-Claude style axis. It routes you to the installed CLI's live help via
  shell and shows how to translate that help into the generic `backend_options`
  mechanism. It is not a flag catalog.
version: 0.3.0
last_changed_at: 2026-08-07T00:00:00Z
related_files:
- src/lingtai/tools/daemon/manual/reference/cli-backends/SKILL.md
- src/lingtai/tools/daemon/manual/reference/cli-backends/reference/backends/claude-p/SKILL.md
maintenance: |
  Tracks the Codex daemon backend flag-discovery and operational-core topics it documents; update when that integration changes.
---

# Codex Daemon Backend — Flag Discovery Entrypoint

The installed CLI's own help is the authority for Codex flags; this page is only
the entrypoint. Conversion rules, key safety, and persistence live in the parent
[`reference/cli-backends/SKILL.md`](../../../SKILL.md).

## Discover flags from the installed CLI

1. Run, in bash: `codex --version`, `codex --help`, and `codex exec --help`.
   The daemon backend wraps `codex exec`, so `codex exec --help` is the
   relevant flag surface. These are local read-only commands; no session is
   started.
2. Translate what you found into `backend_options` with the parent's generic
   conversion rules. Nothing Codex-specific is added to that contract here.

## Example: reasoning effort via the generic `config` route

Codex exposes most of its tunables as repeated `-c, --config <key=value>`
overrides (see `codex exec --help` for the key=value syntax). Through
`backend_options`, a list value repeats the flag once per item:

```jsonc
{
  "backend": "codex",
  "tasks": [{
    "task": "Implement and validate the change.",
    "tools": [],
    "backend_options": {
      "config": ["model_reasoning_effort=\"ultra\""]
    }
  }]
}
// argv: --config model_reasoning_effort="ultra"
```

The effort vocabulary belongs to the installed CLI and the selected model —
LingTai does not validate, enumerate, or simulate effort levels. A value like
`ultra` passes through and the CLI/model decides its semantics (or rejects it).

## Installation

```bash
npm install -g @openai/codex@0.130.0
```

Update an existing installation:

```bash
codex update
# or
npm i -g @openai/codex@latest
```

After installing, verify the installed CLI before relying on any flag
(`codex --version`, `codex exec --help` — see "Discover flags" above).

## Configuration

### Auth & API key

Billed through the **ChatGPT subscription** (Plus/Pro) via `codex login`, or a
shared codex-pool (`~/.lingtai-tui/codex-auth-pool.json`). LingTai inherits the
CLI's own credentials.

Alternatively, set an OpenAI API key:

```bash
export OPENAI_API_KEY="your-api-key"
```

or configure it in `~/.codex/config.toml`:

```toml
[api]
key = "your-api-key"
```

**AWS Bedrock:** use console-login credentials — `aws login`, then run codex:

```bash
aws login
codex exec "your prompt"
```

### Models

Codex supports several models:

- `gpt-5.5` (latest, recommended)
- `gpt-5.4`
- `gpt-5.3-codex` (specialized for coding)

Set the default in `~/.codex/config.toml`:

```toml
[model]
default = "gpt-5.5"
```

The model-name vocabulary belongs to the installed CLI and the account — LingTai
does not validate, enumerate, or simulate model names. Per-run model selection
passes through `backend_options` (e.g. `"model": "gpt-5.5"` → `--model
gpt-5.5`) via the parent's generic conversion rules.

## Style axis: Codex vs Claude Code

Codex and Claude Code are both LingTai daemon backends; the choice between them
is about *style*, not just run shape:

- **Codex** — tightly-scoped diffs, deterministic refactors, mechanical
  validation sweeps. More conservative; the right choice when the change is
  well-specified and the scope is clear.
- **Claude Code** — exploratory code reading, multi-file edits, skill/doc work,
  PR composition. See `reference/backends/claude-p/SKILL.md`.

## Capability note

Codex CLI is open source and built in Rust. Beyond the headless `codex exec`
surface the daemon wraps, the CLI also ships an interactive TUI (native Vim
editing, plugin management, hooks) and a Chrome extension, plus a headless
remote-control app-server. Those are interactive features; the daemon backend
only exercises `codex exec`, whose live surface is `codex exec --help` — not a
static catalog here.

Official docs: https://developers.openai.com/codex/

## Harness boundary

Codex currently declares no reserved-flag list at the validation layer, so
nothing is refused for this backend beyond the generic key/value safety rules.
Still, do not re-set harness-owned surfaces (`--json`, sandbox/approval
bypass, or `mcp_servers.daemon_common.*` config keys): breaking them silently
breaks progress/result extraction and completion enforcement.

## Troubleshooting

1. **Installation fails.** Clear the npm cache, then reinstall:

   ```bash
   npm cache clean --force
   npm install -g @openai/codex@0.130.0
   ```

2. **`OPENAI_API_KEY` not found.**

   ```bash
   echo $OPENAI_API_KEY          # environment variable set?
   cat ~/.codex/config.toml      # or the [api] key in the config file
   ```

3. **Plugin installation fails.** Check marketplace connectivity, then clear
   the plugin cache:

   ```bash
   codex plugins search
   rm -rf ~/.codex/plugins/cache
   ```

4. **Agent appears stuck while `codex exec` runs.** You likely used synchronous
   CLI for work that should have been daemon-backed or supervised in the
   background. Inspect the child process and worktree; if needed, kill the
   child so the blocking call returns, then resume with the Codex daemon
   backend or a supervised background wrapper that records logs, timeout,
   cancellation path, and recovery notes.

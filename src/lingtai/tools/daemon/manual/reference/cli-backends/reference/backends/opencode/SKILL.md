---
name: daemon-backend-opencode
description: >
  Nested daemon-cli-backends reference for the OpenCode daemon backend's flag
  surface and operational setup (install, auth, run flags, warm server,
  custom agents). Read this when a daemon task needs OpenCode-specific CLI
  flags (model selection, provider-specific reasoning variants, agent choice)
  or OpenCode install/auth preparation: it routes you to the installed CLI's
  live help via shell and shows how to translate that help into the generic
  `backend_options` mechanism. It is not a flag catalog.
version: 0.4.0
last_changed_at: 2026-08-07T00:00:00Z
related_files:
- src/lingtai/tools/daemon/manual/reference/cli-backends/SKILL.md
maintenance: |
  Tracks the OpenCode daemon backend flag-discovery and operational-core topics it documents; update when that integration changes.
---

# OpenCode Daemon Backend — Flag Discovery Entrypoint

The installed CLI's own help is the authority for OpenCode flags; this page is
only the entrypoint. Conversion rules, key safety, and persistence live in the
parent [`reference/cli-backends/SKILL.md`](../../../SKILL.md). This page also
owns the OpenCode operational core (install, auth, run flags, warm server,
custom agents) migrated from the retired `shell-manual` bash reference.

## Install & verify

```bash
# Official install script
curl -fsSL https://opencode.ai/install | bash

# Or install with a Node.js package manager
npm install -g opencode-ai      # also works with bun/pnpm/yarn

# Confirm it is on PATH
opencode --version
```

## Discover flags from the installed CLI

1. Run, in bash: `opencode --version`, `opencode --help`, and
   `opencode run --help`. The daemon backend wraps `opencode run`, so
   `opencode run --help` is the relevant flag surface. These are local
   read-only commands; no session is started.
2. Translate what you found into `backend_options` with the parent's generic
   conversion rules. Nothing OpenCode-specific is added to that contract here.

## Example: model and reasoning variant

OpenCode selects models as `provider/model` via `-m, --model`, and exposes
provider-specific reasoning effort as `--variant` (see `opencode run --help`
for both). Through `backend_options`, plain scalars become `--flag <value>`:

```jsonc
{
  "backend": "opencode",
  "tasks": [{
    "task": "Implement and validate the change.",
    "tools": [],
    "backend_options": {
      "model": "anthropic/claude-sonnet-4-5",
      "variant": "high"
    }
  }]
}
// argv: --model anthropic/claude-sonnet-4-5 --variant high
```

The model and variant vocabularies belong to the installed CLI and the selected
provider — LingTai does not validate, enumerate, or simulate them.

## Condensed `opencode run` flag surface

Illustrative, not a catalog — verify every flag against `opencode run --help`
on the installed CLI before relying on it in automation; OpenCode moves
quickly. Through `backend_options`, plain scalars become `--flag <value>`.

| Flag | Purpose |
|------|---------|
| `--dir DIR` | Run in a directory (or remote path when using `--attach`) |
| `--model PROVIDER/MODEL` / `-m` | Choose model, e.g. `openai/gpt-5.5`, `anthropic/claude-sonnet-4-5` |
| `--variant VALUE` | Provider-specific reasoning effort / model variant |
| `--agent NAME` | Use a named OpenCode agent |
| `--file PATH` / `-f` | Attach file(s) to the message |
| `--format json` | Raw JSON events for scripts — harness-owned for daemon runs (see Harness boundary) |
| `--continue` / `-c` | Continue the last session — harness-owned for daemon runs |
| `--session ID` / `-s` | Continue a specific session — harness-owned for daemon runs |
| `--fork` | Fork when continuing a session — harness-owned for daemon runs |
| `--attach URL` | Attach the run to an existing `opencode serve` backend |
| `--password PASSWORD` | Password for attaching to a warm `opencode serve` backend (see Warm server below) |
| `--dangerously-skip-permissions` | Auto-approve permissions not explicitly denied. Dangerous; only use in an externally sandboxed worktree. |

## Subscription & auth

Authenticate at least one provider before relying on OpenCode for work:

```bash
opencode auth login          # interactive provider selection
opencode auth login -p openai
opencode auth list           # or: opencode auth ls
```

OpenCode stores provider credentials in `~/.local/share/opencode/auth.json`
and also loads provider keys from the environment and from a project `.env`
file. For the curated **OpenCode Go** subscription use the `opencode-go`
preset with `OPENCODE_GO_API_KEY` and `https://opencode.ai/zen/go/v1` (chat
wire only).

Official docs: https://opencode.ai/docs/

## Warm server for repeated calls

Starting a fresh OpenCode run can cold-boot MCP servers. For many short calls,
keep a server warm:

```bash
# Session 1: save a generated password where another shell can read it
pwfile=/tmp/opencode-server-password
openssl rand -hex 16 > "$pwfile"
chmod 600 "$pwfile"
OPENCODE_SERVER_PASSWORD="$(cat "$pwfile")" opencode serve --port 4096

# Session 2: read the same password and attach
opencode run --attach http://localhost:4096 \
  --password "$(cat /tmp/opencode-server-password)" \
  --dir /path/to/repo \
  "Explain async/await in this codebase"
```

## Custom agent with constrained permissions

Deny-by-default: `opencode agent create` denies any omitted permission in the
generated agent frontmatter.

```bash
mkdir -p .opencode/agent
opencode agent create \
  --path .opencode/agent/reviewer.md \
  --description "Read-only reviewer for docs and code diffs" \
  --mode primary \
  --permissions read,grep,glob

opencode run --agent reviewer "Review this diff; do not edit files."
```

Available permissions include `bash`, `read`, `edit`, `glob`, `grep`,
`webfetch`, `task`, `todowrite`, `websearch`, `lsp`, and `skill`.

## Harness boundary

OpenCode reserves `--format` at the validation layer: the daemon owns
`opencode run --format json` so its per-line JSON event parsing keeps working,
and passing `--format` in `backend_options` refuses the whole batch before
spawn. Beyond that, do not re-set harness-owned surfaces: session flags
(`--session` / `--continue`) belong to `daemon(action="ask", input={"id": ..., "message": ...})` resume
(`opencode run --session <opencode_session_id> --format json ...`), and the
completion MCP is injected through the `OPENCODE_CONFIG_CONTENT` environment
variable — not argv — so breaking either silently breaks progress/result
extraction and completion enforcement.

In `daemon.json`, OpenCode's `backend_harness_argv` holds a sentinel token pair
that the runner converts into the `OPENCODE_CONFIG_CONTENT` environment variable
rather than real argv flags.

## Key Commands

| Command | Purpose |
|---------|---------|
| `opencode run [message...]` | Run non-interactively and exit |
| `opencode serve` | Start a headless HTTP server for API/attached runs |
| `opencode attach [url]` | Attach a terminal to an existing backend server |
| `opencode auth login/list/logout` | Manage provider credentials |
| `opencode agent create/list` | Manage custom OpenCode agents |
| `opencode mcp add/list/auth/logout/debug` | Manage MCP servers |
| `opencode models` / `opencode models --refresh` | List or refresh provider/model cache |

## Best Practices

1. **Use a clean worktree.** OpenCode can edit files. Isolate risky runs in
   `/tmp/...` worktrees so you can inspect or discard changes safely.
2. **Set `--dir` explicitly.** Avoid running against the wrong repository when
   the bash working directory is ambiguous.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `opencode: command not found` | Install with `npm install -g opencode-ai`, then confirm `$(npm prefix -g)/bin` is on PATH (or use your package manager's global-bin command). |
| No provider/model available | Run `opencode auth login`, check environment variables / project `.env`, then `opencode models --refresh`. |
| Wrong repository edited | Stop, inspect `git diff`, and rerun with explicit `--dir /path/to/repo` in a disposable worktree. |
| Permission prompts hang automation | Prefer a custom agent with explicit permissions; if externally sandboxed, use `--dangerously-skip-permissions`. |
| Slow repeated calls | Use `opencode serve` and `opencode run --attach http://localhost:4096 ...`. |
| Session continuation hits the wrong thread | Use `--session <id>` instead of `--continue`; add `--fork` for experiments. |

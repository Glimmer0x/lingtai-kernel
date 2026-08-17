---
name: daemon-backend-deepseek
description: >
  Nested daemon-cli-backends reference for the DeepSeek Harness daemon
  backend's flag surface. Read this only when a daemon task needs
  DeepSeek-specific launcher flags (`--patch` overlays): it routes you to the
  installed CLI's live help via shell and shows how to translate that help into
  the generic `backend_options` mechanism. It is not a flag catalog.
version: 0.1.0
last_changed_at: 2026-08-16T00:00:00Z
related_files:
- src/lingtai/tools/daemon/manual/reference/cli-backends/SKILL.md
maintenance: |
  Tracks the DeepSeek Harness daemon backend flag-discovery topic it documents; update when that integration changes.
---

# DeepSeek Harness Daemon Backend — Flag Discovery Entrypoint

The installed CLI's own help is the authority for DeepSeek Harness flags; this
page is only the entrypoint. Conversion rules, key safety, and persistence live
in the parent [`reference/cli-backends/SKILL.md`](../../../SKILL.md). `deepseek`
is the canonical backend name (no alias is registered); persisted daemon
entries use it verbatim.

## Discover flags from the installed CLI

1. Run, in bash: `dsh --help` (launcher help) and, once the headless profile
   has booted at least once, `dsh --profile headless --help` (the headless
   app's own help). The daemon backend wraps the one-shot headless profile
   (`dsh --profile headless <prompt>`), which takes only the task text as its
   positional argument — there is no `exec`-style wrapper subcommand. These are
   local read-only commands; no session is started. The docs authority is the
   official CLI reference: https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/cli/reference/README.md
2. Translate what you found into `backend_options` with the parent's generic
   conversion rules. Nothing DeepSeek-specific is added to that contract here.

## Example: launcher-level `--patch` overlay

The launcher parses its own flags first; the first unrecognized token starts
`--profile headless`'s app arguments. Only launcher-level flags are therefore
meaningful in `backend_options` for this backend — the highest-value one is
`--patch <path>`, the official way to overlay a config tree (provider/model
selection) on a one-shot run. Through `backend_options`, a string value becomes
`--flag <value>`:

```jsonc
{
  "backend": "deepseek",   // no alias; canonical name only
  "tasks": [{
    "task": "Implement and validate the change.",
    "tools": [],
    "backend_options": {
      "patch": "./dsh-model.yml",   // launcher flag + value
      "env": {
        "DEEPSEEK_API_KEY": "sk-..."  // only if the operator's env lacks it
      }
    }
  }]
}
// argv: dsh --patch ./dsh-model.yml --profile headless <prompt>
```

The model/provider vocabulary belongs to the installed CLI and its patch/settings
configuration — LingTai does not validate, enumerate, or simulate model names.
Non-launcher flags (e.g. `--model ...`) are NOT valid here: they end up as app
arguments after the launcher boundary and the headless app rejects them as a
usage error (exit 1 → the run fails with the CLI's stderr).

## Subscription & auth

The DeepSeek Harness base bundle mounts the native DeepSeek adapter
(`deepseek-official` route; default models deepseek-v4-flash / deepseek-v4-pro).
Credentials resolve from the inherited environment first (`DEEPSEEK_API_KEY` is
the adapter's default `apiKeyEnv`; `$DEEPSEEK_BASE_URL` overrides the public
API), then `$DSH_HOME/.credentials.yaml`, the invoking project's `.env`, then
`$DSH_HOME/.env`. LingTai pins `$DSH_HOME` to the run-private `<run>/dsh-home`
so the headless profile's first-use auto-initialization and per-profile settings
never touch the operator's real home — the machine-local `cordis.patch.yml` /
`.credentials.yaml` layers are therefore deliberately NOT honored; use env vars
or the project's `.env`. Never print key values.

Official docs: https://github.com/deepseek-ai/deepseek-harness (developer
preview — upstream may break compatibility between releases).

## Harness boundary

DeepSeek Harness declares a reserved-flag list at the validation layer; passing
any of these in `backend_options` refuses the whole batch before spawn:
`--profile`, `--dump-default-config`, `--dump-config`, `--version`, `--help`.
LingTai owns `--profile headless` (the one-shot harness's profile lock) and the
inspection-only exits are reserved because they would finish without doing the
task. `--patch` is intentionally NOT reserved (documented user knob, same trust
level as `backend_options.env`). No stable machine-readable session-id / resume
contract was verified for the shipped headless profile, so
`daemon(action="ask", input={"id": ..., "message": ...})` returns an explicit unsupported-backend error — start
a new deepseek emanation instead.

Free-form options are inserted between `dsh` and the owned `--profile headless`
flags; the prompt is the headless app's trailing positional argument. Output is
plain text, not a JSON event stream: stdout is recorded verbatim, line by line,
as `cli_output` events, no session id is captured, and the joined stdout becomes
the result (exit 0 = completed; any nonzero exit — usage error, boot/config
failure, or non-completed session — fails the run with the recorded text kept
in the run dir for inspection). The run-private env (`DSH_HOME`, and
`DSH_TELEMETRY_DISABLED=1` — the official hard opt-out) plus the operator's
`$DSH_HOME` caveat are described in the parent table; `daemon_common` MCP
injection is not wired yet for this backend.

## DeepSeek-specific validation steps

In the Generic validation checklist (see
`reference/cli-backends/SKILL.md`), additionally confirm from installed help
that the launcher's app-argument boundary behaves as documented (`dsh --profile
headless "task"` prints the final answer and exits 0/1, and non-launcher flags
after the boundary are rejected by the headless app). Before enabling `ask` for
this backend, source-cite a stable machine-readable session-id output plus a
tested resume command from local help/code — do not guess.

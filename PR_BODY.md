## What

Adds a `ShellKind` classifier (posix / powershell / cmd / gitbash / wsl) that is the **single authority** for both the spawn argv the kernel passes to `subprocess` and the model-facing shell description. The technique mirrors what Cline (`buildRunCommandsDescription`), Claude Code, and Goose (`shell_display_name`) do: tell the model which shell dialect it is actually using, per request, inside the tool description.

## Why

Different shells need different spawn forms (`[pwsh -NoLogo -NoProfile -NonInteractive -Command]` vs `[cmd /d /s /c]` vs `[bash -lc]` vs `wsl.exe -e bash -lc`), different quoting rules, and different sequencing semantics (Windows PowerShell 5.1 has no `&&`; cmd.exe has no `;` separator). The model only gets a string description at setup time, so the description must state the shell + the correct chaining/sequencing idiom.

## Design

- `ShellKind` enum in `tools/bash/_shell_dialect.py` with per-kind: `display_name`, `sequencing_guidance` (e.g. PowerShell -> "Sequence commands with ';' - '&&' is not supported by Windows PowerShell 5.1"), and the **one** `_SPAWN_ARGV_BY_KIND` table. `make_invocation_for_kind()` builds every spawn form from that table - no scattered if/else over shell names.
- `resolve_shell_kind()` in `adapters/shell.py` (the outer composition selector): explicit `shell_setting` (init.json `manifest.capabilities.shell.shell_kind` -> `setup(shell_kind=...)`) > `LINGTAI_SHELL` env var > platform default (POSIX on Unix; PowerShell when `pwsh` is discoverable on Windows, then Git Bash, then cmd.exe). WSL is opt-in only. Invalid overrides fall back to the platform default instead of breaking setup.
- New thin dialects for the opt-in/fallback kinds: `CmdDialect`, `GitBashDialect`, `WslDialect` (Git Bash / WSL reuse the POSIX command extractor; cmd gets a conservative `&`/`|`/newline splitter that only over-denies under an allowlist).
- Runtime metadata: `ShellManager.shell_kind` property + durable async job state gains `shell_kind` next to `shell_dialect`; `setup()` passes the resolved kind into `get_description()` so the tool description names the shell and its sequencing idiom.

## Behavior preservation

- Default cases are byte-identical: POSIX keeps the historical `shell=True` form (`ShellInvocation(script=...)`), PowerShell keeps `[pwsh -NoLogo -NoProfile -NonInteractive -Command]` with the existing exit-code wrapper and utf-8/replace decode. Existing tests (incl. PR1 contract argv pins) pass unchanged.
- Windows default remains PowerShell; the only behavior change is on a Windows host **without pwsh**, which previously failed setup with `FileNotFoundError` and now degrades to Git Bash (if present) then cmd.exe.
- cmd.exe command matching is now case-insensitive in policy checks (like PowerShell), since cmd names are case-insensitive.

## Config

`LINGTAI_SHELL` is documented in `ENVIRONMENT_VARIABLES.md` (accepted values `posix`, `powershell`, `cmd`, `gitbash`, `wsl`; unknown values fall back to the platform default).

## Tests

- `tests/test_shell_kind_classifier.py`: classifier unit tests with platform simulated via monkeypatch (posix default; Windows pwsh/gitbash/cmd fallback chain; env + init.json override precedence; WSL never auto-selected; coerce/from_state_key; guidance contents).
- `tests/test_shell_kind_spawn_args.py`: golden spawn-argv tests per kind (`make_invocation_for_kind` + each dialect), description prose checks, `setup(shell_kind="cmd")` end-to-end, manager runtime metadata + durable state key, unknown-dialect fallback.

Ran green: `test_bash_shell_dialect.py`, `test_shell_pr1_contract.py`, `test_shell_kind_classifier.py`, `test_shell_kind_spawn_args.py`, `test_shell_tool_family_migration.py`, `test_layers_bash.py`, `test_bash_async_process_contract.py`, `test_shell_sandbox_containment.py`, `test_shell_windows_state_lock_args.py`, `test_bash_async.py` (248 tests).

## Scope / non-duplication

Read batch-1 PRs #1182-#1189 before writing this: pwsh well-known-path discovery (#1182) and the quote-aware metachar scanner (#1188) are **not** reimplemented - the classifier probes `shutil.which("pwsh")` (the same probe `PowerShellDialect` uses today) and leaves the metachar scanner untouched.

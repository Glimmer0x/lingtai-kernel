# Batch-2 PR B5 - ShellKind classifier (ps/pr-b5-shellkind-classifier)

PR: https://github.com/Lingtai-AI/lingtai-kernel/pull/1190 (OPEN, base `main`, head `ps/pr-b5-shellkind-classifier`)
Worktree: /tmp/ps-pr-b5 (branch `ps/pr-b5-shellkind-classifier`, one commit on top of `main` @ 3b5b3738)

## What shipped

A `ShellKind` enum/classifier (posix / powershell / cmd / gitbash / wsl) that drives BOTH the
subprocess spawn argv and the model-facing shell tool description, in one place.

### Files changed (+791 / -27, 12 files)
- `src/lingtai/tools/bash/_shell_dialect.py` - `ShellKind` enum, the ONE `_SPAWN_ARGV_BY_KIND`
  table, `display_name`/`sequencing_guidance` metadata, `make_invocation_for_kind()` (single spawn
  authority), `ShellDialect.kind()`.
- `src/lingtai/adapters/shell.py` - `resolve_shell_kind()` classifier (shell_setting > LINGTAI_SHELL
  > platform default: POSIX / Windows pwsh -> gitbash -> cmd; WSL opt-in only) + `_dialect_for()`
  factory + `select_shell_dialect(shell_kind=...)`.
- `src/lingtai/adapters/posix/bash.py`, `src/lingtai/adapters/windows/powershell.py` - route
  `make_invocation` through the kind-keyed authority (argv byte-identical to before).
- NEW `src/lingtai/adapters/windows/cmd.py` (CmdDialect + conservative cmd extractor),
  `gitbash.py` (GitBashDialect + discover_git_bash), `wsl.py` (WslDialect + discover_wsl).
- `src/lingtai/tools/bash/__init__.py` - `ShellManager.shell_kind` property + `shell_kind` in durable
  async job state + `setup(shell_kind=...)` kwarg (init.json capability override) + cmd
  case-insensitive policy matching.
- `src/lingtai/tools/bash/_tool_family.py` - `get_description(...)` now names the active shell and
  prints sequencing guidance (e.g. PowerShell -> "Sequence commands with ';' - '&&' is not supported
  by Windows PowerShell 5.1"). Legacy phrase "Active shell dialect: X" preserved.
- `ENVIRONMENT_VARIABLES.md` - LINGTAI_SHELL row added.
- NEW `tests/test_shell_kind_classifier.py`, `tests/test_shell_kind_spawn_args.py`.

## Behavior preservation
- POSIX default: historical `shell=True` form, byte-identical.
- Windows default (pwsh present): `[pwsh -NoLogo -NoProfile -NonInteractive -Command]` + existing
  wrapper, identical. Only Windows-without-pwsh changes: previously failed setup, now degrades to
  Git Bash then cmd.exe.
- No duplication of batch-1: pwsh well-known-path discovery (#1182) and metachar scanner (#1188)
  untouched; classifier probes `shutil.which("pwsh")` exactly like `PowerShellDialect`.

## Validation
- 248 tests green with full-deps venv
  (/home/huangzesen/.lingtai-tui/runtime/venv/bin/python): test_bash_shell_dialect,
  test_shell_pr1_contract, test_shell_kind_classifier, test_shell_kind_spawn_args,
  test_shell_tool_family_migration, test_layers_bash, test_bash_async_process_contract,
  test_shell_sandbox_containment, test_shell_windows_state_lock_args, test_bash_async.
- The 2 failures in test_shell_tool_family_migration (missing `openai` module) are pre-existing on
  main in the default python3.10 env; they pass under the venv.

## Remaining risks
- cmd/gitbash/wsl paths are exercised on POSIX CI only via unit/golden tests; native Windows smoke
  coverage would strengthen them (the repo's windows-native suite runs on windows-latest).
- WSL spawn uses the Windows `cwd` passed to wsl.exe (no --cd remap); documented as opt-in niche.
- LINGTAI_SHELL is read at shell-tool setup time; a restart is required to change it.

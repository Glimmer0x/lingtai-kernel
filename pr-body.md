## Problem

#1376's opt-in risky-action gate was merged but Fable's independent whole-review found it **bypassable** — it cannot be published as a security boundary. An opted-in deployment could be silently bypassed by ordinary shell syntax and by the daemon/compat paths.

## Bypass vectors closed

1. **Glued redirection** — `printf pwn>/tmp/x`, `echo hi >>/tmp/x` survived `_command_segments` as a single token (verb `printf`/`echo` is read-only) and were allowed. `_CHAIN_SEPARATORS` now also splits on `>> > << < |&`, so redirection always lands in its own segment and is denied.
2. **Path-form executable** — `./ls` was basename-trusted as the system `ls`. A `./path` executable is now denied outright (`path-form executable ... is not a bare read-only verb`).
3. **`env` execution redirect** — `env PATH=/attacker ls`, `env LD_PRELOAD=/attacker.so ls`, `env PYTHONPATH=/attacker python3 ...` were unwrapped to a read-only verb. `_unwrap` now returns `None` (fail closed) when an assignment touches `PATH`/`LD_PRELOAD`/`DYLD_INSERT_LIBRARIES`/`PYTHONPATH`/`PERL5LIB`/`RUBYLIB`/`NODE_PATH`/`GEM_HOME`/`GEM_PATH`/`ENV`/`BASH_ENV`/`PYTHONSTARTUP`.
4. **Git list-only subcommands** — `git branch pwn`, `git tag v1`, `git remote add x y` were allowed because `branch`/`tag`/`remote` were classified read-only. Those subcommands are now list-only: a positional argument is denied; bare `git branch`, `git tag`, `git remote -v`, `git status`, `git log -1` remain allowed.
5. **Read-only verb with write flag** — `sort -o /tmp/x input`, `curl -o /tmp/x ...`, `wget -O /tmp/x ...` were allowed. `_READ_ONLY_WRITE_FLAGS` (`-o`/`--output`/`-O`/`--outfile`/`-i`/`--in-place`) on a read-only verb is now denied.
6. **Daemon stub had no guard** — `DaemonSupervisorAgentStub` set `_tool_call_guard = None`, so daemon tool dispatch bypassed an opted-in gate. The stub now wires `ToolCallGuard([build_risky_action_check(working_dir)])` (same opt-in root as the parent agent).
7. **Compat `bash` name** — the gate only checked `tool_name == "shell"`, but the registry maps compat `bash` → `shell` after guard evaluation. The gate now treats `bash` the same as `shell`.
8. **Expired approval resurrection** — `mark_approval` accepted an approval on a request whose TTL had already elapsed. It now checks expiry inline (fail closed: malformed timestamp → expired; expired can never become approved).

## Validation

- `tests/test_risky_action_gate.py`: 16/16 passed (9 new regression tests cover every Fable probe: glued redirection, append redirection, path-form executable, env PATH/LD_PRELOAD/PYTHONPATH, git branch/tag/remote positional vs list forms, read-only verb write flags, compat bash name, daemon stub guard, inline expired approval).
- Adjacent regression: test_daemon stub/guard subset 1/1, guard suites 26/26, 43 passed / 0 failed. Whole-tree collection in the local interpreter hits 70 pre-existing env ABI errors (python3.14 interpreter vs python3.13 venv pydantic/cffi) — unrelated, reproduces on base.
- `compileall` + `git diff --check` clean; canonical `Huang Zesen <hzsbazinga@outlook.com>`.

Telegram: @lingtaidev3bot | Nickname: 澄一
Powered by LingTai AI: https://github.com/Lingtai-AI/lingtai
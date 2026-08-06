"""Windows regression tests mirroring Hermes/OpenClaw CI coverage.

Covers the three Windows adapter contracts that silently regress on POSIX CI:

* wrapper argv stays ``-NoLogo -NoProfile -NonInteractive`` (Hermes
  ``test_windows_subprocess_no_window_flags.py`` pattern);
* spawn hides the console window and suspends the child until it is assigned
  to the kill-on-close Job Object;
* the pwsh wrapper preserves native exit codes (``exit 42`` from a native
  command must surface 42 through our PowerShell dialect) instead of collapsing
  them to PowerShell's generic 0/1;
* ``extract_commands`` token boundaries: command substitutions and script
  blocks recurse, dynamic/malformed syntax fails closed with the
  ``__powershell_unsupported__`` sentinel.

Pure-string tests (wrapper construction, ``extract_commands``) run on every
platform; only the spawn/creationflags test genuinely requires Windows and is
skipped elsewhere.
"""
from __future__ import annotations

import subprocess
import sys
from unittest import mock

import pytest

from lingtai.adapters.windows.powershell import PowerShellDialect
from lingtai.adapters.windows.powershell_process import WindowsShellAsyncProcessAdapter

_PWSH = "pwsh"
_UNSUPPORTED = "__powershell_unsupported__"
# Win32 process creation flags the adapter must keep passing (see
# powershell_process.py): hide the console window, create a new process group,
# and start suspended so the Job Object can own the tree before it runs.
_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_CREATE_SUSPENDED = 0x00000004


@pytest.fixture(scope="module")
def dialect() -> PowerShellDialect:
    """A PowerShell dialect pinned to a fixed executable name (no pwsh needed)."""
    return PowerShellDialect(executable=_PWSH)


class TestWrapperFlags:
    """The wrapper argv must keep its no-startup-noise, non-interactive shape."""

    def test_wrapper_uses_no_logo_no_profile_no_interactive(self, dialect):
        invocation = dialect.make_invocation("Write-Output hi")
        args, kwargs = invocation.process_args()
        # executable + argv + script; argv carries the four pwsh switches.
        assert args[0] == _PWSH
        assert args[1:5] == ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]
        # The wrapped script travels over UTF-8 stdin (never the command
        # line); argv ends in the ASCII bootstrap and is never shell=True.
        assert invocation.stdin_script == invocation.script
        assert "[Console]::In.ReadToEnd()" in args[-1]
        assert kwargs == {"shell": False}
        assert invocation.encoding == "utf-8"
        assert invocation.errors == "replace"


class TestNativeExitCodeFidelity:
    """Unit tests for the wrapper suffix; run on every platform."""

    def test_native_exit_code_fidelity(self, dialect):
        script = "& $env:ComSpec /d /c exit 42"
        wrapped = dialect.make_invocation(script).script
        # The user script runs verbatim inside the wrapper.
        assert script in wrapped
        # 7.3+ exposes native failures as typed errors so ``pwsh -Command`` no
        # longer collapses them to a generic 0/1 process status.
        assert "$PSNativeCommandUseErrorActionPreference = $true" in wrapped
        assert "ProgramExitedWithNonZeroCode" in wrapped
        assert "$PSNativeCommandUseErrorActionPreference = $__lingtai_old_native_pref" in wrapped
        # ``$?`` is captured at the end of the user's final pipeline and the
        # native code is read from ``$LASTEXITCODE`` without rewriting it.
        assert "$global:__lingtai_success = $?" in wrapped
        assert "[int]$global:LASTEXITCODE" in wrapped
        assert "$global:LASTEXITCODE = 0" not in wrapped
        # Exit branches in order: success -> 0, native failure -> the captured
        # code (42 for ``cmd /c exit 42``), anything else -> 1.
        assert "exit $global:__lingtai_native_exit" in wrapped
        assert wrapped.index("exit 0") < wrapped.index("exit $global:__lingtai_native_exit")
        assert wrapped.index("exit $global:__lingtai_native_exit") < wrapped.index("exit 1")

    def test_wrapper_does_not_rewrite_native_exit_between_statements(self, dialect):
        script = "& $env:ComSpec /d /c exit 42; if ($LASTEXITCODE -ne 42) { throw 'lost' }"
        wrapped = dialect.make_invocation(script).script
        # The wrapper never fabricates a zero for a failed native command, so
        # PowerShell-level ``$LASTEXITCODE`` checks inside the script keep their
        # native semantics.
        assert "$global:LASTEXITCODE = 0" not in wrapped
        assert script in wrapped


class TestExtractCommandsTokenBoundaries:
    """Command substitutions and script blocks recurse; unsafe forms fail closed."""

    @pytest.mark.parametrize(
        "script, expected",
        [
            # Substitutions recurse into the nested command.
            ("Write-Output $(Remove-Item victim)", ("Write-Output", "Remove-Item")),
            # Script blocks recurse into the nested command.
            ("ForEach-Object { Remove-Item victim }", ("ForEach-Object", "Remove-Item")),
            # Mixed pipeline, block, and substitution keep boundary order.
            (
                "Write-Output hi | ForEach-Object { $_ }; Write-Output $(Get-Date)",
                ("Write-Output", "ForEach-Object", "Write-Output", "Get-Date"),
            ),
            # Control-flow keywords are skipped but the guarded body is inspected.
            ("if ($true) { Remove-Item victim }", ("Remove-Item",)),
            # A statically-known quoted call target is accepted.
            ("& 'Remove-Item' victim", ("Remove-Item",)),
            # Dynamic invocation targets fail closed with the sentinel.
            ("& $command", (_UNSUPPORTED,)),
            ('& "$command" victim', (_UNSUPPORTED,)),
            # Malformed substitution / unbalanced groups fail closed.
            ("$(Remove-Item victim", (_UNSUPPORTED,)),
            ("Write-Output (Remove-Item victim", (_UNSUPPORTED,)),
            ("Write-Output ()", (_UNSUPPORTED,)),
            ("Write-Output )", (_UNSUPPORTED,)),
            # Backtick-escaped command names are lexically ambiguous; reject.
            ("Rem`ove-Item victim", (_UNSUPPORTED,)),
        ],
    )
    def test_extract_commands_token_boundaries(self, dialect, script, expected):
        assert dialect.extract_commands(script) == expected

    def test_extract_commands_sentinel_is_never_a_real_command(self, dialect):
        # The sentinel must never be admitted through policy; a regression here
        # would let deny/allow lists treat dynamic syntax as a command name.
        extracted = dialect.extract_commands("& $command; Remove-Item victim")
        assert extracted == (_UNSUPPORTED, "Remove-Item")


@pytest.mark.skipif(sys.platform != "win32", reason="no-window spawn flags are a Windows-only contract")
class TestSpawnNoWindowFlags:
    """Native spawn must keep hiding the console and suspending before Job assignment."""

    def test_spawn_passes_no_window_creationflags_and_wrapper_argv(self, monkeypatch, tmp_path, dialect):
        import lingtai.adapters.windows.powershell_process as process_adapter

        invocation = dialect.make_invocation("Write-Output hi")
        popen = mock.MagicMock()
        monkeypatch.setattr(process_adapter.subprocess, "Popen", popen)
        # Keep the ctypes/Job machinery out of the way: this test asserts the
        # spawn *arguments*, not kernel32 behavior.
        monkeypatch.setattr(process_adapter, "_new_job_for_process", lambda process: None)
        monkeypatch.setattr(process_adapter, "_resume_suspended_process", lambda process: None)
        monkeypatch.setattr(process_adapter, "_ref", lambda pid: object())

        stdout_path = tmp_path / "stdout"
        stderr_path = tmp_path / "stderr"
        adapter = WindowsShellAsyncProcessAdapter()
        ref, owned = adapter.spawn(invocation, str(tmp_path), stdout_path, stderr_path)
        try:
            args, kwargs = popen.call_args
            argv = args[0]
            assert argv[1:5] == ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command"]
            # The wrapped script travels over UTF-8 stdin; argv ends in the
            # ASCII bootstrap that reads stdin and runs the script.
            assert "[Console]::In.ReadToEnd()" in argv[-1]
            assert invocation.stdin_script == invocation.script
            creationflags = kwargs["creationflags"]
            # Never flash a console window for the pwsh child (Hermes
            # test_windows_subprocess_no_window_flags.py pattern).
            assert creationflags & _CREATE_NO_WINDOW == _CREATE_NO_WINDOW
            assert creationflags & _CREATE_NEW_PROCESS_GROUP == _CREATE_NEW_PROCESS_GROUP
            # Suspended spawn closes the spawn-to-Job-assignment ownership race.
            assert creationflags & _CREATE_SUSPENDED == _CREATE_SUSPENDED
            assert kwargs["close_fds"] is True
            # The wrapped script is delivered over a UTF-8 stdin pipe (the
            # ASCII bootstrap reads it); never DEVNULL for the pwsh child.
            assert kwargs["stdin"] is subprocess.PIPE
        finally:
            owned.close()

"""PR-5: quote-aware PowerShell metachar safety scanner contract."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from lingtai.adapters.windows.powershell import (
    WINDOWS_ALWAYS_UNSAFE_TOKENS,
    WINDOWS_UNSUPPORTED_TOKENS,
    PowerShellDialect,
    is_unsafe_windows_command,
    windows_wrapper_escalation_reason,
)
from lingtai.tools.bash import ShellManager, ShellPolicy


SAFE_COMMANDS = [
    "Get-Process",
    "Get-Content 'C:\\temp\\file.txt'",
    # Double quotes quote most metacharacters for PowerShell.
    'Write-Output "hello & goodbye"',
    # Single quotes ARE quoting for PowerShell (unlike cmd.exe).
    "Write-Output 'hello & goodbye'",
    "Write-Output 'it''s'",  # '' escapes a quote inside single quotes
    # Nested quotes stay balanced and literal.
    "Write-Output \"a 'b' c\"",
    "Write-Output 'a \"b\" c'",
    # $ is literal inside single quotes.
    "Write-Output '$HOME'",
    "Write-Output '$env:TEMP'",
    "Get-ChildItem -Filter '*.txt'",
    "Remove-Item -LiteralPath .\\victim",
]

UNSAFE_CASES = [
    # Metachars outside quotes.
    ("Get-Process; Remove-Item x", "metachar ';'"),
    ("Get-Process | Stop-Process", "metachar '|'"),
    ("echo hello & echo world", "metachar '&'"),
    ("Get-Content < file.txt", "metachar '<'"),
    ("echo out > file.txt", "metachar '>'"),
    ("echo ^&", "metachar '^'"),
    ("(Get-Process)", "metachar '('"),
    ("Get-Process)", "metachar ')'"),
    ("echo !history!", "metachar '!'"),
    # % / backtick / newlines are always unsafe (even quoted).
    ("echo %PATH%", "metachar '%'"),
    ("echo `n", "metachar '`'"),
    ("Get-Process\nRemove-Item", "newline"),
    ("Get-Process\rRemove-Item", "newline"),
    ('Write-Output "50% done"', "metachar '%'"),
    ('Write-Output "`t"', "metachar '`'"),
    ('Write-Output "a\nb"', "newline"),
    ("Write-Output '50% done'", "metachar '%'"),
    ("Write-Output '`n'", "metachar '`'"),
    # $ variable expansion anywhere outside single quotes.
    ("Get-ChildItem $env:TEMP", "variable expansion"),
    ('Write-Output "$env:TEMP"', "variable expansion"),
    ("Write-Output $(Get-Date)", "variable expansion"),
    ("Write-Output ${env:USERNAME}", "variable expansion"),
    ("Write-Output $?", "variable expansion"),
    ("Write-Output $$", "variable expansion"),
    ("Write-Output $_", "variable expansion"),
]

ESCALATION_CASES = [
    ("pwsh -EncodedCommand AAEAAABLAQAA", "-EncodedCommand"),
    ("powershell.exe -e AAEAAABLAQAA", "-EncodedCommand"),
    ("pwsh -enc AAEAAABLAQAA", "-EncodedCommand"),
    ("pwsh /EncodedCommand AAEAAABLAQAA", "-EncodedCommand"),
    ("pwsh -File C:\\scripts\\setup.ps1", "-File"),
    ("powershell -f setup.ps1", "-File"),
    ("pwsh -Command Get-Process", "profile startup before inline command"),
    ("pwsh -c Get-Process", "profile startup before inline command"),
    ("pwsh -Command 'Get-Process'", "profile startup before inline command"),
    ("pwsh -Command -", "stdin payload"),
    ("pwsh -NoProfile -Command -", "stdin payload"),
    ("pwsh", "bare wrapper invocation (profile/stdin)"),
    ("pwsh -", "stdin payload"),
    ("pwsh -NoExit -Command Get-Process", "unreviewed startup flag -NoExit"),
    ("pwsh setup.ps1", "script file argument before inline command"),
    ("pwsh -- -Command Get-Process", "-- stop-parsing marker"),
]

NO_ESCALATION_CASES = [
    "pwsh -NoProfile -Command Get-Process",
    "powershell -NoProfile -NonInteractive -Command Get-Process",
    "pwsh -NoProfile -c Write-Output hi",
    "pwsh -NoProfile --command Get-Process",
    "pwsh -NoProfile -Command 'Write-Output hi'",
    "Get-Process",
    "node script.js",
    "cmd /c echo hi",
]


@pytest.mark.parametrize("command", SAFE_COMMANDS)
def test_scanner_accepts_safe_commands(command):
    unsafe, reason = is_unsafe_windows_command(command)
    assert unsafe is False, f"{command!r} should be safe, got reason {reason!r}"


@pytest.mark.parametrize("command, reason", UNSAFE_CASES)
def test_scanner_flags_unsafe_commands(command, reason):
    unsafe, found = is_unsafe_windows_command(command)
    assert unsafe is True
    assert found == reason


def test_token_tables_match_openclaw():
    assert WINDOWS_UNSUPPORTED_TOKENS == frozenset(
        {"&", "|", "<", ">", ";", "^", "(", ")", "%", "!", "`", "\n", "\r"}
    )
    assert WINDOWS_ALWAYS_UNSAFE_TOKENS == frozenset({"\n", "\r", "%", "`"})
    assert WINDOWS_ALWAYS_UNSAFE_TOKENS <= WINDOWS_UNSUPPORTED_TOKENS


@pytest.mark.parametrize("command, reason", ESCALATION_CASES)
def test_wrapper_escalation_flags_unbound_payloads(command, reason):
    found = windows_wrapper_escalation_reason(command)
    assert found == reason


@pytest.mark.parametrize("command", NO_ESCALATION_CASES)
def test_wrapper_escalation_accepts_bound_payloads(command):
    assert windows_wrapper_escalation_reason(command) is None


def test_dialect_extract_commands_fails_closed_on_flagged_commands():
    dialect = PowerShellDialect(executable="pwsh")
    assert dialect.extract_commands("Get-Process") == ("Get-Process",)
    assert dialect.extract_commands('Write-Output "a & b"') == ("Write-Output",)
    assert dialect.extract_commands("Get-Process; Remove-Item x") == (
        "__powershell_unsupported__",
    )
    assert dialect.extract_commands("Get-ChildItem $env:TEMP") == (
        "__powershell_unsupported__",
    )
    assert dialect.extract_commands("pwsh -EncodedCommand AAEAAABLAQAA") == (
        "__powershell_unsupported__",
    )
    assert dialect.extract_commands("pwsh -File setup.ps1") == (
        "__powershell_unsupported__",
    )
    assert dialect.extract_commands("pwsh -Command Get-Process") == (
        "__powershell_unsupported__",
    )
    assert dialect.extract_commands("pwsh -NoProfile -Command Get-Process") == ("pwsh",)


@pytest.mark.parametrize(
    "policy",
    [ShellPolicy(deny=["Remove-Item"]), ShellPolicy(allow=["Write-Output"])],
)
@pytest.mark.parametrize(
    "command",
    [
        "Get-Process; Remove-Item victim",
        "Get-ChildItem $env:TEMP",
        'Write-Output "$(Get-Date)"',
        "pwsh -EncodedCommand AAEAAABLAQAA",
        "pwsh -File setup.ps1",
        "pwsh -Command Get-Process",
        "echo %PATH%",
    ],
)
def test_flagged_commands_require_human_confirmation_under_policy(tmp_path, policy, command):
    dialect = PowerShellDialect(executable="pwsh")
    dialect.make_invocation = MagicMock(side_effect=AssertionError("pwsh must not run"))
    manager = ShellManager(
        policy=policy,
        working_dir=str(tmp_path),
        agent=SimpleNamespace(),
        dialect=dialect,
    )
    denied = manager.handle({"command": command})
    assert denied["status"] == "error"
    assert "does not support this syntax" in denied["message"]
    assert "refusing to run" in denied["message"]
    dialect.make_invocation.assert_not_called()


def test_flagged_commands_still_run_under_yolo_policy(tmp_path):
    dialect = PowerShellDialect(executable="pwsh")
    dialect.make_invocation = MagicMock(
        return_value=PowerShellDialect(executable="pwsh").make_invocation("Get-Process")
    )
    manager = ShellManager(
        policy=ShellPolicy.yolo(),
        working_dir=str(tmp_path),
        agent=SimpleNamespace(),
        dialect=dialect,
    )
    result = manager.handle({"command": "Get-Process; Stop-Process"})
    # yolo mode deliberately passes the original script to pwsh; the scanner
    # only escalates when a policy is configured.
    dialect.make_invocation.assert_called_once_with("Get-Process; Stop-Process")
    assert result["status"] == "error"  # pwsh is not installed on this host

"""PowerShell 7 dialect adapter for the shell language Port.

This adapter intentionally does not reuse the POSIX extractor.  It recognizes
PowerShell statement/pipeline boundaries and recursively inspects command
substitutions and script blocks.  Unsupported dynamic syntax is represented by
a sentinel command so a configured allowlist/denylist fails closed; trusted
(yolo) execution can still pass the original script to pwsh.
"""
from __future__ import annotations

import os
import re
import shutil
import sys

from lingtai.tools.bash._shell_dialect import (
    ShellDialect,
    ShellInvocation,
    ShellKind,
    make_invocation_for_kind,
)

_UNSUPPORTED = "__powershell_unsupported__"

# ASCII-only ``pwsh -Command`` bootstrap (Cline's technique,
# sdk/packages/shared/src/parse/shell.ts).  PowerShell decodes ``-Command``
# through the active Windows console code page, so user source must never
# travel on the command line; the bootstrap reads the entire command from
# stdin as UTF-8, appends an exit-status check, and runs it as a ScriptBlock.
# Feeding stdin instead of the cmdline also lifts Windows' 32,768-character
# process command-line limit and keeps arbitrary UTF-8 source intact.
_ASCII_BOOTSTRAP = (
    "[Console]::InputEncoding=[Text.UTF8Encoding]::new();"
    "[Console]::OutputEncoding=[Text.UTF8Encoding]::new();"
    "$c=[Console]::In.ReadToEnd();"
    "$c+=[Environment]::NewLine+'if(-not $?){exit 1}';"
    "& ([ScriptBlock]::Create($c))"
)
_CONTROL_WORDS = {
    "begin", "break", "catch", "class", "continue", "data", "do", "else",
    "end", "finally", "for", "foreach", "function", "if", "param", "process",
    "return", "switch", "throw", "trap", "try", "until", "using", "while",
}
_ASSIGNMENT_RE = re.compile(r"^(?:\$[A-Za-z_][\w:]*|[A-Za-z_][\w-]*)$")
_TOKEN_RE = re.compile(
    r"(?:'[^']*(?:''[^']*)*'|\"(?:`.|[^\"])*\"|&(?=\s|$)|\.(?=\s|$)|[^\s|;&(){}]+)"
)


def _balanced_inner(script: str, start: int, opener: str, closer: str) -> tuple[str, int] | None:
    """Return a balanced region, respecting PowerShell quote/backtick rules."""
    depth = 1
    quote: str | None = None
    escaped = False
    i = start + 1
    while i < len(script):
        char = script[i]
        if quote == "'":
            if char == "'":
                if i + 1 < len(script) and script[i + 1] == "'":
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "`":
                escaped = True
            elif char == '"':
                quote = None
            i += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return script[start + 1 : i], i + 1
        i += 1
    return None


def _split_statements(script: str) -> tuple[list[str], bool]:
    """Split top-level PowerShell statements and report malformed quoting."""
    pieces: list[str] = []
    begin = 0
    i = 0
    quote: str | None = None
    escaped = False
    paren_depth = 0
    while i < len(script):
        char = script[i]
        if quote == "'":
            if char == "'":
                if i + 1 < len(script) and script[i + 1] == "'":
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "`":
                escaped = True
            elif char == '"':
                quote = None
            i += 1
            continue
        if char in {"'", '"'}:
            quote = char
            i += 1
            continue
        if char == "(":
            paren_depth += 1
        elif char == ")":
            if paren_depth == 0:
                return pieces, False
            paren_depth -= 1
        if char in "|;\r\n" and paren_depth == 0:
            pieces.append(script[begin:i])
            if char == "|" and i + 1 < len(script) and script[i + 1] in "|&":
                i += 1
            elif char == "&" and i + 1 < len(script) and script[i + 1] == "&":
                i += 1
            begin = i + 1
        elif char == "&" and i + 1 < len(script) and script[i + 1] == "&" and paren_depth == 0:
            pieces.append(script[begin:i])
            i += 1
            begin = i + 1
        i += 1
    pieces.append(script[begin:])
    return pieces, quote is None and paren_depth == 0


def _is_quoted_at(script: str, index: int) -> bool:
    """Return whether ``index`` is inside a PowerShell quoted string."""
    quote: str | None = None
    escaped = False
    i = 0
    while i < index:
        char = script[i]
        if quote == "'":
            if char == "'":
                if i + 1 < index and script[i + 1] == "'":
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "`":
                escaped = True
            elif char == '"':
                quote = None
            i += 1
            continue
        if char in {"'", '"'}:
            quote = char
        i += 1
    return quote is not None


def _commands(script: str) -> tuple[str, ...]:
    pieces, well_formed = _split_statements(script)
    if not well_formed:
        return (_UNSUPPORTED,)
    result: list[str] = []
    for piece in pieces:
        text = piece.strip()
        if not text:
            continue
        # Recursively inspect substitutions and script blocks before removing
        # them from the outer statement.  Dynamic invocation cannot be proved.
        remainder: list[str] = []
        nested: list[str] = []
        i = 0
        while i < len(text):
            if text.startswith("$(", i):
                region = _balanced_inner(text, i + 1, "(", ")")
                if region is None:
                    result.append(_UNSUPPORTED)
                    break
                nested.extend(_commands(region[0]))
                i = region[1]
                continue
            if text[i] == "{" or (text[i] == "@" and i + 1 < len(text) and text[i + 1] == "{"):
                opener_at = i if text[i] == "{" else i + 1
                region = _balanced_inner(text, opener_at, "{", "}")
                if region is None:
                    result.append(_UNSUPPORTED)
                    break
                nested.extend(_commands(region[0]))
                i = region[1]
                continue
            if text[i] == "(" and not _is_quoted_at(text, i):
                region = _balanced_inner(text, i, "(", ")")
                if region is None or not region[0].strip():
                    result.append(_UNSUPPORTED)
                    break
                nested.extend(_commands(region[0]))
                i = region[1]
                continue
            if text[i] == ")" and not _is_quoted_at(text, i):
                result.append(_UNSUPPORTED)
                break
            remainder.append(text[i])
            i += 1
        else:
            outer = "".join(remainder).strip()
            tokens = _TOKEN_RE.findall(outer)
            if not tokens:
                result.extend(nested)
                continue
            # A call/dot-source operator is syntax, not the command being
            # invoked.  Only an unquoted literal or a single-quoted literal is
            # statically knowable; variables, expandable strings, and array or
            # subexpression targets must fail closed under policy enforcement.
            index = 0
            if tokens[0] in {"&", "."}:
                if len(tokens) < 2:
                    result.append(_UNSUPPORTED)
                    result.extend(nested)
                    continue
                target = tokens[1]
                if target.startswith(("$", "@", '"', "`")):
                    result.append(_UNSUPPORTED)
                    result.extend(nested)
                    continue
                if target.startswith("'") and not target.endswith("'"):
                    result.append(_UNSUPPORTED)
                    result.extend(nested)
                    continue
                index = 2
                first = target[1:-1].replace("''", "'") if target.startswith("'") else target
            else:
                first = tokens[0].strip("'\"")
            # Skip assignments and PowerShell control syntax.  A bare control
            # statement without a block is unsupported rather than guessed.
            while index + 2 < len(tokens) and _ASSIGNMENT_RE.fullmatch(tokens[index]) and tokens[index + 1] == "=":
                index += 2
            if index == 0:
                if index >= len(tokens):
                    result.extend(nested)
                    continue
                first = tokens[index].strip("'\"")
            if "`" in first:
                # PowerShell accepts backticks inside unquoted command names as
                # lexical escapes (for example ``Rem`ove-Item``).  Decoding every
                # valid form requires a real PowerShell lexer; configured policy
                # must instead reject the ambiguous identity conservatively.
                result.append(_UNSUPPORTED)
                result.extend(nested)
                continue
            if first.casefold() in _CONTROL_WORDS:
                result.extend(nested)
                continue
            if first.startswith("$") or first.startswith("@"):
                # A variable/array expression in a script block is data, not a
                # command.  Dynamic invocation was already rejected at ``& $x``.
                result.extend(nested)
                continue
            result.append(first)
            result.extend(nested)
    return tuple(result)


def _well_known_pwsh_paths() -> tuple[str, ...]:
    r"""Return the registry-free well-known PowerShell 7 install locations.

    Mirrors OpenClaw's ``resolvePowerShellPath`` order on Windows:
    ``%ProgramFiles%\PowerShell\7\pwsh.exe`` then
    ``%ProgramW6432%\PowerShell\7\pwsh.exe``.  Only consulted on Windows;
    other platforms rely on the PATH lookup alone.
    """
    if sys.platform != "win32":
        return ()
    paths: list[str] = []
    for env_var in ("ProgramFiles", "ProgramW6432"):
        root = os.environ.get(env_var)
        if root:
            paths.append(os.path.join(root, "PowerShell", "7", "pwsh.exe"))
    return tuple(paths)


def _find_pwsh() -> str | None:
    """Locate the PowerShell 7 executable (``pwsh``).

    Checks the well-known PowerShell 7 install directories first (Windows
    only), then a PATH lookup via ``shutil.which``.  Windows PowerShell 5.1
    (``powershell.exe``) is intentionally never used as a fallback.
    """
    for candidate in _well_known_pwsh_paths():
        if os.path.isfile(candidate):
            return candidate
    return shutil.which("pwsh")


class PowerShellDialect(ShellDialect):
    """PowerShell 7 (``pwsh``) invocation and policy extraction."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or _find_pwsh()
        if not self._executable:
            searched = ", ".join((*_well_known_pwsh_paths(), "'pwsh' on PATH"))
            raise FileNotFoundError(
                "PowerShell 7 executable 'pwsh' was not found. Searched: "
                f"{searched}. Windows shell requires pwsh and never falls "
                "back to Windows PowerShell 5.1. Install PowerShell 7: "
                "winget install Microsoft.PowerShell"
            )

    def extract_commands(self, script: str) -> tuple[str, ...]:
        return _commands(script)

    def make_invocation(self, script: str) -> ShellInvocation:
        # ``pwsh -Command`` otherwise collapses an external program's native
        # exit status to PowerShell's generic 0/1 process status.  PowerShell
        # 7.3+ can expose non-zero native results as a typed ErrorRecord without
        # changing command flow.  Capture that final-operation type together
        # with ``$?`` and ``$LASTEXITCODE`` inside the user's script scope.
        # Crucially, the wrapper never resets or rewrites ``$LASTEXITCODE``
        # between user statements, so ordinary PowerShell status checks retain
        # their native semantics.
        #
        # Transport: the wrapped payload below is byte-for-byte what used to be
        # passed as the ``-Command`` argument, so the existing escape/quote and
        # exit-code handling is preserved as the stdin payload.  The command
        # line itself carries only the fixed ASCII ``_ASCII_BOOTSTRAP``: user
        # source travels over UTF-8 stdin instead of the Windows command line,
        # which avoids code-page mangling of the ``-Command`` argument, the
        # 32,768-character process command-line limit, and UTF-8 in/out
        # problems (the bootstrap forces Input/OutputEncoding to UTF-8).
        wrapped = (
            "$global:__lingtai_success = $false\n"
            "$global:__lingtai_native_exit = 0\n"
            "$global:__lingtai_final_native_failure = $false\n"
            "$__lingtai_old_native_pref = $PSNativeCommandUseErrorActionPreference\n"
            "try {\n"
            "  $PSNativeCommandUseErrorActionPreference = $true\n"
            "  & {\n"
            f"{script}\n"
            # These assignments run in the same runtime scope as the user's
            # final pipeline, before the wrapper performs any later command.
            "    $global:__lingtai_success = $?\n"
            "    $global:__lingtai_native_exit = [int]$global:LASTEXITCODE\n"
            "    $global:__lingtai_final_native_failure = (\n"
            "      (-not $global:__lingtai_success) -and\n"
            "      ($Error.Count -gt 0) -and\n"
            "      ($Error[0].FullyQualifiedErrorId -eq 'ProgramExitedWithNonZeroCode')\n"
            "    )\n"
            "  }\n"
            "} catch {\n"
            "  $global:__lingtai_success = $false\n"
            "  $global:__lingtai_native_exit = [int]$global:LASTEXITCODE\n"
            "  $global:__lingtai_final_native_failure = (\n"
            "    $_.FullyQualifiedErrorId -eq 'ProgramExitedWithNonZeroCode'\n"
            "  )\n"
            "  if (-not $global:__lingtai_final_native_failure) {\n"
            "    [Console]::Error.WriteLine($_.ToString())\n"
            "  }\n"
            "} finally {\n"
            "  $PSNativeCommandUseErrorActionPreference = $__lingtai_old_native_pref\n"
            "}\n"
            "if ($global:__lingtai_success) { exit 0 }\n"
            "if ($global:__lingtai_final_native_failure -and "
            "$global:__lingtai_native_exit -ne 0) {\n"
            "  exit $global:__lingtai_native_exit\n"
            "}\n"
            "exit 1\n"
        )
        # Spawn shape comes from the single ShellKind-keyed authority so the
        # argv template stays in lockstep with the model-facing description.
        invocation = make_invocation_for_kind(
            ShellKind.POWERSHELL, wrapped, executable=self._executable,
        )
        # Layer the ASCII stdin bootstrap on top of the authority shape: the
        # wrapped script must travel over UTF-8 stdin (never the ``-Command``
        # line) to dodge the Windows console code page and the 32,768-character
        # process command-line limit.  ``stdin_script`` tells the spawner to
        # feed the child from stdin; the bootstrap is the final ``-Command``
        # argument that reads stdin and runs the script.
        return ShellInvocation(
            script=wrapped,
            stdin_script=wrapped,
            executable=invocation.executable,
            argv=invocation.argv + (_ASCII_BOOTSTRAP,),
            encoding=invocation.encoding,
            errors=invocation.errors,
        )

    def state_key(self) -> str:
        return ShellKind.POWERSHELL.value


__all__ = ["PowerShellDialect"]

"""PowerShell 7 dialect adapter for the shell language Port.

This adapter intentionally does not reuse the POSIX extractor.  It recognizes
PowerShell statement/pipeline boundaries and recursively inspects command
substitutions and script blocks.  Unsupported dynamic syntax is represented by
a sentinel command so a configured allowlist/denylist fails closed; trusted
(yolo) execution can still pass the original script to pwsh.

The extractor is conservative by design: it only emits statically knowable
command names, strips comments, honours here-strings and backtick line
continuations, skips literals/types/operators as data, and fails closed on
dynamic invocation (call operator on a variable, Invoke-Expression, etc.).
"""
from __future__ import annotations

import codecs
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

from .windows_cmd_shim import try_cmd_shim_plan

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
    "begin", "break", "catch", "class", "continue", "data", "default", "do",
    "else", "elseif", "end", "enum", "exit", "filter", "finally", "for",
    "foreach", "function", "hidden", "if", "in", "param", "process",
    "return", "static", "switch", "throw", "trap", "try", "until", "using",
    "while",
}


def _pwsh_single_quote(arg: str) -> str:
    """Emit ``arg`` as a PowerShell single-quoted literal (embedded ``'`` doubled)."""
    return "'" + arg.replace("'", "''") + "'"


def _pwsh_quote_argv(argv: list[str]) -> str:
    """Render ``argv`` as PowerShell source for ``pwsh -Command``.

    Uses the call operator with every element single-quoted, so the result is
    valid PowerShell for *any* argument: paths with spaces
    (``C:\\Program Files\\nodejs\\node.exe``), apostrophes (``it's`` via
    ``'it''s'``), and ``$``/backtick/``--%`` tokens all stay literal.
    ``subprocess.list2cmdline`` must never be used to generate PS source: its
    C-runtime quoting emits a quoted string in command position, which
    PowerShell rejects with an "Unexpected token" parse error.
    """
    return "& " + " ".join(_pwsh_single_quote(arg) for arg in argv)


# Dynamic evaluation primitives: invoking these with a non-literal argument
# executes arbitrary code, so the whole script must fail closed.
_EVAL_COMMANDS = {"invoke-expression", "iex"}
# Commands that accept a -ScriptBlock; a non-literal block is dynamic.
_SCRIPTBLOCK_COMMANDS = {"invoke-command", "start-job"}
_ASSIGNMENT_RE = re.compile(r"^(?:\$[A-Za-z_][\w:]*|[A-Za-z_][\w-]*)$")
_TOKEN_RE = re.compile(
    r"(?:'[^']*(?:''[^']*)*'|\"(?:`.|[^\"])*\"|&(?=\s|$)|\.(?=\s|$)|[^\s|;&(){}]+)"
)


def _find_here_string_end(script: str, start: int, quote: str) -> int | None:
    """Return the index just past a here-string's closing delimiter.

    ``start`` points at the ``@`` of an ``@'`` or ``@\"`` opener.  The closing
    delimiter (``'@`` / ``\"@``) must appear at the start of a line (allowing
    leading whitespace), per PowerShell syntax.  Returns ``None`` when the
    here-string is unterminated.
    """
    pos = start + 2
    needle = quote + "@"
    while pos < len(script):
        nl = script.find("\n", pos)
        if nl == -1:
            return None
        j = nl + 1
        while j < len(script) and script[j] in " \t":
            j += 1
        if script.startswith(needle, j):
            return j + 2
        pos = nl + 1
    return None


def _strip_comments(script: str) -> str:
    """Remove PowerShell ``#`` comments outside quotes/here-strings."""
    out: list[str] = []
    i = 0
    n = len(script)
    quote: str | None = None
    hs: str | None = None
    while i < n:
        ch = script[i]
        if hs:
            if ch == "\n":
                j = i + 1
                while j < n and script[j] in " \t":
                    j += 1
                if j + 1 < n and script[j] == hs and script[j + 1] == "@":
                    out.append(script[i:j + 2])
                    hs = None
                    i = j + 2
                    continue
            out.append(ch)
            i += 1
            continue
        if quote == "'":
            out.append(ch)
            if ch == "'":
                if i + 1 < n and script[i + 1] == "'":
                    out.append("'")
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if quote == '"':
            out.append(ch)
            if ch == "`" and i + 1 < n:
                out.append(script[i + 1])
                i += 2
                continue
            if ch == '"':
                quote = None
            i += 1
            continue
        if ch == "#":
            while i < n and script[i] != "\n":
                i += 1
            continue
        if ch == "@" and i + 1 < n and script[i + 1] in ("'", '"'):
            hs = script[i + 1]
            out.append(ch)
            out.append(hs)
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


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
        if char == "@" and i + 1 < len(script) and script[i + 1] in ("'", '"'):
            end = _find_here_string_end(script, i, script[i + 1])
            if end is None:
                return None
            i = end
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
    brace_depth = 0  # Track brace depth for script blocks
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
        if char == "@" and i + 1 < len(script) and script[i + 1] in ("'", '"'):
            # Here-string: consume the whole body; quotes inside are literal.
            end = _find_here_string_end(script, i, script[i + 1])
            if end is None:
                return pieces, False
            i = end
            continue
        if char in {"'", '"'}:
            quote = char
            i += 1
            continue
        if char == "`" and i + 1 < len(script) and script[i + 1] == "\n":
            # Backtick line continuation: do not split at the newline.
            i += 2
            continue
        if char == "(":
            paren_depth += 1
        elif char == ")":
            if paren_depth == 0:
                return pieces, False
            paren_depth -= 1
        elif char == "{":  # Track brace depth
            brace_depth += 1
        elif char == "}":  # Track brace depth
            if brace_depth > 0:
                brace_depth -= 1
        if char in "|;\r\n" and paren_depth == 0 and brace_depth == 0:
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
    return pieces, quote is None and paren_depth == 0 and brace_depth == 0


def _is_quoted_at(script: str, index: int) -> bool:
    """Return whether ``index`` is inside a PowerShell quoted string or here-string."""
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
        if char == "@" and i + 1 < len(script) and script[i + 1] in ("'", '"'):
            end = _find_here_string_end(script, i, script[i + 1])
            if end is None:
                return True  # unterminated here-string: treat the rest as quoted
            if index < end:
                return True
            i = end
            continue
        if char in {"'", '"'}:
            quote = char
        i += 1
    return quote is not None


def _is_data_token(token: str) -> bool:
    """Return True for tokens that are data, not a command name."""
    if not token:
        return True
    first = token[0]
    if first in "'\"$@`":
        return True
    if first.isdigit():
        return True
    if first in "-:?=[].#":
        return True
    return False


def _has_dynamic_scriptblock(tokens: tuple[str, ...], start: int) -> bool:
    """Return True when a -ScriptBlock argument after ``start`` is non-literal.

    A literal ``{ ... }`` block is consumed into ``nested`` by the char scan and
    does not appear in the token list, so ``-ScriptBlock`` as the last token is
    static; only a variable/expandable token after it is dynamic.
    """
    for idx in range(start, len(tokens)):
        if tokens[idx].casefold() == "-scriptblock":
            if idx + 1 >= len(tokens):
                return False
            return tokens[idx + 1].startswith(("$", "@", '"', "`"))
    return False




def _commands(script: str) -> tuple[str, ...]:
    script = _strip_comments(script)
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
            if text[i] == "@" and i + 1 < len(text) and text[i + 1] in ("'", '"'):
                # Here-string: data, never commands.
                end = _find_here_string_end(text, i, text[i + 1])
                if end is None:
                    result.append(_UNSUPPORTED)
                    break
                i = end
                continue
            if text.startswith("$(", i) and not _is_quoted_at(text, i):
                region = _balanced_inner(text, i + 1, "(", ")")
                if region is None:
                    result.append(_UNSUPPORTED)
                    break
                nested.extend(_commands(region[0]))
                i = region[1]
                continue
            if (text[i] == "{" or (text[i] == "@" and i + 1 < len(text) and text[i + 1] == "{")) \
                    and not _is_quoted_at(text, i):
                opener_at = i if text[i] == "{" else i + 1
                region = _balanced_inner(text, opener_at, "{", "}")
                if region is None:
                    result.append(_UNSUPPORTED)
                    break
                nested.extend(_commands(region[0]))
                i = region[1]
                continue
            if text[i] == "(" and not _is_quoted_at(text, i):
                prev_j = i - 1
                while prev_j >= 0 and text[prev_j].isspace():
                    prev_j -= 1
                if prev_j >= 0 and text[prev_j] in "&.":
                    # & (Get-Command ...) / . (Get-Command ...): dynamic target.
                    result.append(_UNSUPPORTED)
                    break
                # F1: eval-command call form ``IEX(...)`` / ``iex(...)`` /
                # ``Invoke-Expression(...)`` -- the eval head glued directly to
                # a group is dynamic invocation even when a member chain
                # follows (``IEX(New-Object).DownloadString``), so fail closed
                # instead of emitting the head as a literal command. The
                # backward name scan accepts ``-`` so canonical ``Verb-Noun``
                # eval cmdlets (``Invoke-Expression``) are recovered whole,
                # not truncated to ``Expression``.
                head_start = i
                while head_start > 0 and (
                    text[head_start - 1].isalnum()
                    or text[head_start - 1] in ("_", "-")
                ):
                    head_start -= 1
                if text[head_start:i].casefold() in _EVAL_COMMANDS:
                    result.append(_UNSUPPORTED)
                    break
                if i > 0 and text[i - 1] == "@":
                    # @(...) array literal: values are data unless they name
                    # a command (e.g. @(Get-Process)).
                    region = _balanced_inner(text, i, "(", ")")
                    if region is None:
                        result.append(_UNSUPPORTED)
                        break
                    if region[0].strip():
                        nested.extend(_commands(region[0]))
                    i = region[1]
                    continue
                region = _balanced_inner(text, i, "(", ")")
                if region is None:
                    result.append(_UNSUPPORTED)
                    break
                if not region[0].strip():
                    # Empty parens: method call ($x.ToString()) or attribute
                    # ([CmdletBinding()]) are data; a bare empty group after a
                    # command (Write-Output ()) stays unsupported.
                    prev = text[i - 1] if i > 0 else ""
                    if prev.isalnum() or prev in "_$].`":
                        i = region[1]
                        continue
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
            emitted = False
            unsupported = False
            suppress_nested = False
            index = 0
            while index < len(tokens):
                tok = tokens[index]
                # Skip assignment LHS: any ``token =`` pair is data.
                if index + 1 < len(tokens) and tokens[index + 1] == "=":
                    index += 2
                    continue
                if tok in {"&", "."}:
                    if index + 1 >= len(tokens):
                        if tok == "&" and nested and not emitted:
                            # & { ... } static script-block target.
                            result.extend(nested)
                            emitted = True
                            break
                        unsupported = True
                        break
                    target = tokens[index + 1]
                    if target.startswith(("$", "@", '"', "`")):
                        unsupported = True
                        break
                    if target.startswith("'") and not target.endswith("'"):
                        unsupported = True
                        break
                    first = target[1:-1].replace("''", "'") if target.startswith("'") else target
                    if "`" in first:
                        unsupported = True
                        break
                    result.append(first)
                    emitted = True
                    break
                low = tok.casefold()
                if low in _CONTROL_WORDS:
                    if low in {"function", "class", "enum", "filter"}:
                        # Skip the declared name after these keywords.
                        if index + 1 < len(tokens):
                            index += 2
                        else:
                            index += 1
                        if low == "enum":
                            suppress_nested = True
                        continue
                    index += 1
                    continue
                if _is_data_token(tok):
                    index += 1
                    continue
                if "`" in tok:
                    unsupported = True
                    break
                if low in _EVAL_COMMANDS:
                    unsupported = True
                    break
                if low in _SCRIPTBLOCK_COMMANDS and _has_dynamic_scriptblock(tokens, index):
                    unsupported = True
                    break
                result.append(tok.strip("'\""))
                result.extend(nested)
                emitted = True
                break
            if unsupported:
                result.append(_UNSUPPORTED)
                result.extend(nested)
            elif not emitted and not suppress_nested:
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


_OEM_CODEPAGE_GUESSES = ("cp437", "cp850", "cp1252")
_UTF8_BOM = b"\xef\xbb\xbf"


def _oem_text_score(text: str) -> int:
    """Lower is better: penalize C0 controls and non-Latin characters.

    Every single-byte codepage decodes every byte, so a first-successful-decode
    fallback would always pick ``cp437`` and never reach ``cp850``/``cp1252``.
    Scoring instead prefers the candidate whose bytes look most like text: C0
    controls signal binary data, and characters beyond Latin Extended-B (box
    drawing, Greek, ...) are rarely produced by OEM text tools.  U+FFFD
    replacement characters score too, so the same metric can compare an OEM
    interpretation against a mostly-intact UTF-8 interpretation of a line.
    """
    score = 0
    for char in text:
        value = ord(char)
        if value < 32 and char not in "\t\n\r":
            score += 5
        elif value > 0x24F:
            score += 2
        elif value > 0xFF:
            score += 1
    return score


def _is_tail_truncation(line: bytes) -> bool:
    """True when ``line`` ends with an incomplete multibyte UTF-8 sequence.

    A log read that catches the child mid-write can tear a multibyte character
    at the end of the file.  The incremental decoder only reports that at
    finalization, after successfully consuming every byte as a valid prefix;
    mid-line invalid bytes (the genuine OEM case) fail during consumption and
    return False.
    """
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        decoder.decode(line)
    except UnicodeDecodeError:
        return False
    try:
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return True
    return False


def _decode_windows_line(line: bytes) -> str:
    """Decode one captured line: strict UTF-8, then per-line OEM fallback.

    A whole-file OEM fallback is deliberately avoided: as soon as *any* byte
    run in a mostly-UTF-8 log is invalid (one native tool that re-enabled the
    OEM codepage, or a torn multibyte character from a read that caught the
    child mid-write), re-decoding the entire file as cp437/cp850/cp1252 turns
    the previously valid Chinese/emoji text into box-drawing mojibake.
    Deciding per line confines the fallback to the lines that actually contain
    non-UTF-8 bytes, and the remaining heuristics keep sparse damage sparse:

    - a torn multibyte character at the end of the line is replaced (one
      U+FFFD), never re-interpreted as OEM bytes;
    - a line that still decodes to genuine non-ASCII UTF-8 text keeps that
      text even when it also contains invalid bytes (only those bytes are
      replaced);
    - only otherwise-Latin lines with invalid bytes are re-decoded with the
      OEM codepage guesses, and only when the OEM text scores better than the
      ``errors="replace"`` version of the same bytes.
    """
    try:
        return line.decode("utf-8")
    except UnicodeDecodeError:
        pass
    utf8_replaced = line.decode("utf-8", errors="replace")
    if _is_tail_truncation(line):
        return utf8_replaced
    if any(ch != "\ufffd" and ord(ch) > 127 for ch in utf8_replaced):
        return utf8_replaced
    best: tuple[int, str] | None = None
    for codepage in _OEM_CODEPAGE_GUESSES:
        try:
            text = line.decode(codepage)
        except UnicodeDecodeError:
            continue
        score = _oem_text_score(text)
        if best is None or score < best[0]:
            best = (score, text)
    if best is not None and best[0] < _oem_text_score(utf8_replaced):
        return best[1]
    return utf8_replaced


def decode_windows_output(data: bytes) -> str:
    """Decode captured child output: strict UTF-8 first, then OEM per line.

    The PowerShell wrapper forces ``[Console]::OutputEncoding`` and
    ``$OutputEncoding`` to UTF-8, so native commands normally emit valid UTF-8
    bytes.  A leading UTF-8 BOM is stripped, and a buffer that is entirely
    valid UTF-8 is returned as-is.  If any byte run is invalid, the fallback
    is decided *per line* (see ``_decode_windows_line``) with the common
    Windows OEM codepages (cp437/cp850/cp1252 heuristics) instead of
    re-decoding the whole file or corrupting the invalid bytes with
    ``errors="replace"``.  Line endings are preserved byte-for-byte; callers
    normalize CRLF (the bash read-back boundary translates ``\r\n``/``\r`` to
    ``\n`` exactly like the historical ``read_text``).  This function never
    raises.
    """
    if data.startswith(_UTF8_BOM):
        data = data[len(_UTF8_BOM):]
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # 0x0A is a line break in UTF-8 and in every OEM codepage and never
    # occurs inside a multibyte sequence, so the split never tears a
    # character.  Re-join with the same separators, preserving the original
    # line endings (a trailing newline survives via the empty final part).
    parts = data.split(b"\n")
    return "\n".join(_decode_windows_line(part) for part in parts)
# ---------------------------------------------------------------------------
# PR-5: quote-aware Windows metachar safety scanner.
#
# Mirrors OpenClaw's findWindowsUnsupportedToken / WINDOWS_UNSUPPORTED_TOKENS
# with PowerShell quote semantics: single quotes ARE quoting for PowerShell
# (unlike cmd.exe), double quotes protect most metacharacters, and
# % / backtick / newlines stay unsafe in every quote state because cmd.exe
# expands %VAR% and re-parses quoted payloads while PowerShell treats ` as an
# escape character.
# ---------------------------------------------------------------------------

WINDOWS_UNSUPPORTED_TOKENS = frozenset(
    {"&", "|", "<", ">", ";", "^", "(", ")", "%", "!", "`", "\n", "\r"}
)
# Stay unsafe even inside double quotes: newlines break parsing, cmd.exe
# expands %VAR%, and PowerShell treats ` as an escape character.
WINDOWS_ALWAYS_UNSAFE_TOKENS = frozenset({"\n", "\r", "%", "`"})
_WINDOWS_VAR_HEAD_RE = re.compile(r"[A-Za-z0-9_{(?$]")


def _unsafe_reason(token: str) -> str:
    """Stable human-readable reason for a flagged scanner token."""
    if token in "\n\r":
        return "newline"
    if token == "$":
        return "variable expansion"
    return f"metachar {token!r}"


def is_unsafe_windows_command(command: str) -> tuple[bool, str]:
    """Scan ``command`` for PowerShell metacharacters that can hide execution.

    Quote-aware state machine over the OpenClaw token table: ``& | < > ; ^ ( )
    % ! ` \\n \\r`` are flagged outside quotes; ``%`` / backtick / newlines
    are flagged even inside double quotes; and ``$`` followed by
    ``[A-Za-z0-9_{(?$]`` (PowerShell variable expansion, including ``$1``..``$9``
    positional variables) is flagged anywhere except inside single quotes,
    where PowerShell treats it as literal text.

    Returns ``(unsafe, reason)``.  ``reason`` is a stable string naming the
    first flagged token when ``unsafe`` is true, otherwise ``""``.
    """
    in_single = False
    in_double = False
    i = 0
    n = len(command)
    while i < n:
        char = command[i]
        if in_single:
            # Single-quoted PowerShell strings are literal, but the always-
            # unsafe tokens stay flagged: a quoted segment may later reach
            # cmd.exe or Invoke-Expression where %VAR% and backticks execute.
            if char in WINDOWS_ALWAYS_UNSAFE_TOKENS:
                return True, _unsafe_reason(char)
            if char == "'":
                if i + 1 < n and command[i + 1] == "'":
                    i += 2
                    continue
                in_single = False
            i += 1
            continue
        if in_double:
            if char in WINDOWS_ALWAYS_UNSAFE_TOKENS:
                return True, _unsafe_reason(char)
            if char == "$" and i + 1 < n and _WINDOWS_VAR_HEAD_RE.fullmatch(command[i + 1]):
                return True, _unsafe_reason("$")
            if char == '"':
                in_double = False
            i += 1
            continue
        if char in {"'", '"'}:
            if char == "'":
                in_single = True
            else:
                in_double = True
            i += 1
            continue
        if char == "$" and i + 1 < n and _WINDOWS_VAR_HEAD_RE.fullmatch(command[i + 1]):
            return True, _unsafe_reason("$")
        if char in WINDOWS_UNSUPPORTED_TOKENS:
            return True, _unsafe_reason(char)
        i += 1
    return False, ""


def _expand_power_switch_prefix_forms(match: str, smallest: str) -> frozenset[str]:
    """Bare prefix forms PowerShell accepts for a switch (mirrors OpenClaw)."""
    return frozenset(match[:length] for length in range(len(smallest), len(match) + 1))


_POWERSHELL_WRAPPER_NAMES = frozenset({"pwsh", "pwsh.exe", "powershell", "powershell.exe"})
_POWERSHELL_INLINE_COMMAND_FLAGS = (
    _expand_power_switch_prefix_forms("command", "c")
    | _expand_power_switch_prefix_forms("commandwithargs", "cwa")
    | frozenset({"cwa"})
)
_POWERSHELL_INLINE_ENCODED_COMMAND_FLAGS = (
    _expand_power_switch_prefix_forms("encodedcommand", "e")
    | _expand_power_switch_prefix_forms("ec", "e")
)
_POWERSHELL_INLINE_FILE_FLAGS = _expand_power_switch_prefix_forms("file", "f")
_POWERSHELL_NO_PROFILE_FLAGS = _expand_power_switch_prefix_forms("noprofile", "nop")
_POWERSHELL_UNREVIEWED_STARTUP_FLAGS = frozenset().union(
    _expand_power_switch_prefix_forms("configurationfile", "conf"),
    _expand_power_switch_prefix_forms("configurationname", "config"),
    _expand_power_switch_prefix_forms("custompipename", "cus"),
    _expand_power_switch_prefix_forms("encodedarguments", "encodeda"),
    frozenset({"ea"}),
    _expand_power_switch_prefix_forms("interactive", "i"),
    _expand_power_switch_prefix_forms("login", "l"),
    _expand_power_switch_prefix_forms("namedpipeservermode", "nam"),
    _expand_power_switch_prefix_forms("noexit", "noe"),
    _expand_power_switch_prefix_forms("psconsolefile", "pscf"),
    frozenset({"pscf"}),
    _expand_power_switch_prefix_forms("servermode", "s"),
    _expand_power_switch_prefix_forms("settingsfile", "settings"),
    _expand_power_switch_prefix_forms("socketservermode", "so"),
    _expand_power_switch_prefix_forms("sshservermode", "ssh"),
    _expand_power_switch_prefix_forms("v2socketservermode", "v2so"),
)


def _tokenize_windows_command(command: str) -> list[str] | None:
    """Split a command into argv-like tokens honoring PowerShell quoting.

    Double quotes and single quotes group text; ``''`` escapes a quote inside
    single quotes and `` ` `` escapes the next character inside double quotes.
    Returns None when quotes are unbalanced (callers must fail closed).
    """
    tokens: list[str] = []
    buf: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(command)
    while i < n:
        char = command[i]
        if in_single:
            if char == "'":
                if i + 1 < n and command[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                in_single = False
            else:
                buf.append(char)
            i += 1
            continue
        if in_double:
            if char == '"':
                in_double = False
            elif char == "`" and i + 1 < n:
                buf.append(command[i + 1])
                i += 2
                continue
            else:
                buf.append(char)
            i += 1
            continue
        if char in " \t":
            if buf:
                tokens.append("".join(buf))
                buf = []
            i += 1
            continue
        if char == "'":
            in_single = True
            i += 1
            continue
        if char == '"':
            in_double = True
            i += 1
            continue
        buf.append(char)
        i += 1
    if in_single or in_double:
        return None
    if buf:
        tokens.append("".join(buf))
    return tokens


def _normalize_power_flag(token: str) -> str | None:
    """Return the bare lowercase form of a PowerShell switch token.

    Accepts ``-flag``, ``--flag``, and ``/flag`` prefixes; returns None for
    tokens that are not switches.
    """
    if not token:
        return None
    if token.startswith("--"):
        body = token[2:]
    elif token.startswith(("-", "/")):
        body = token[1:]
    else:
        return None
    return body.casefold()


def windows_wrapper_escalation_reason(command: str) -> str | None:
    """Return a reason when ``command`` wraps pwsh in a payload that is not
    bound to the approval text, else None.

    Mirrors OpenClaw ``isBlockedShellWrapperCommand`` for the PowerShell
    wrapper kind: ``-EncodedCommand`` and ``-File`` have no reviewable content,
    and profile startup before the inline command runs unreviewed code.
    """
    tokens = _tokenize_windows_command(command)
    if tokens is None:
        return "unbalanced quoting"
    first = 1 if tokens and tokens[0] in ("&", ".") else 0
    if first >= len(tokens):
        return None
    executable = tokens[first].casefold()
    executable = executable.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
    if executable not in _POWERSHELL_WRAPPER_NAMES:
        return None
    argv = tokens[first + 1 :]
    profiles_disabled = False
    command_index: int | None = None
    for index, raw in enumerate(argv):
        if raw == "--":
            return "-- stop-parsing marker"
        if raw == "-":
            return "stdin payload"
        flag = _normalize_power_flag(raw)
        if flag is None:
            # A positional token before any inline-command flag is a mutable
            # script file whose contents are not bound to the approval.
            return "script file argument before inline command"
        if flag in _POWERSHELL_INLINE_ENCODED_COMMAND_FLAGS:
            return "-EncodedCommand"
        if flag in _POWERSHELL_INLINE_FILE_FLAGS:
            return "-File"
        if flag in _POWERSHELL_INLINE_COMMAND_FLAGS:
            command_index = index
            break
        if flag in _POWERSHELL_NO_PROFILE_FLAGS:
            profiles_disabled = True
            continue
        if flag in _POWERSHELL_UNREVIEWED_STARTUP_FLAGS:
            return f"unreviewed startup flag {raw}"
        # Other pwsh switches (-NoLogo, -NonInteractive, -Sta, -Version, ...)
        # do not execute unreviewed code; keep scanning for the command flag.
    if command_index is None:
        # A bare pwsh/powershell invocation runs profiles and keeps consuming
        # stdin; no payload is bound to this approval.
        return "bare wrapper invocation (profile/stdin)"
    if command_index + 1 < len(argv) and argv[command_index + 1] == "-":
        return "stdin payload"
    if not profiles_disabled:
        return "profile startup before inline command"
    return None


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
        # PR-5: a quote-aware metachar scan fails closed before extraction so
        # flagged commands (pipes, chaining, %VAR%, variable expansion, and
        # -EncodedCommand / -File / profile-startup wrappers) require human
        # confirmation instead of being reviewed token-by-token.  Unbalanced-
        # quote (unparseable) scripts fail closed too, via the wrapper walk's
        # "unbalanced quoting" result.  This is a deliberate, signed-off
        # capability regression: the recursive extractor below previously
        # validated such scripts command-by-command (including ``$()``/``{}``
        # and parenthesized nesting), but scanner simplicity and the OpenClaw
        # fail-closed model win over that precision, so any flagged or
        # unparseable script is refused outright under a configured
        # allow/deny policy.  Trusted (yolo) execution still passes the
        # original script to pwsh.
        unsafe, _reason = is_unsafe_windows_command(script)
        if unsafe:
            return (_UNSUPPORTED,)
        if windows_wrapper_escalation_reason(script) is not None:
            return (_UNSUPPORTED,)
        return _commands(script)

    def make_invocation(self, script: str) -> ShellInvocation:
        # Trusted cmd.exe shim handling: when the script is one simple command
        # whose first token resolves to a .cmd/.bat shim (or npm/npx), do not
        # let pwsh call the shim through the ambient cmd.exe.  npm/npx are
        # rewritten to a direct ``node .../npm-cli.js`` invocation that still
        # runs inside the normal pwsh exit-code envelope below; other shims are
        # wrapped in a trusted ``cmd.exe /d /s /c`` invocation with
        # metacharacter rejection (see ``windows_cmd_shim``).  A ``ValueError``
        # here rejects metacharacters that are unsafe under cmd.exe instead of
        # silently reinterpreting them; anything not a simple shim command
        # falls through to the pwsh wrapper unchanged.
        plan = try_cmd_shim_plan(script)
        if plan is not None:
            kind, argv = plan
            if kind == "cmd":
                return ShellInvocation(
                    script=argv[-1],
                    executable=argv[0],
                    argv=tuple(argv[1:-1]),
                    encoding="utf-8",
                    errors="replace",
                )
            # npm/npx: direct node invocation of the CLI script, still wrapped
            # in the pwsh exit-code envelope (no cmd.exe involved).  The
            # payload is PowerShell *source*, so it is built with the call
            # operator plus PS-native single-quoting (see ``_pwsh_quote_argv``)
            # -- never ``subprocess.list2cmdline``, whose C-runtime quoting
            # produces a quoted string in command position and breaks on the
            # default Windows layout ``C:\Program Files\nodejs\``.
            script = _pwsh_quote_argv(argv)
        return self._pwsh_invocation(script)

    def _pwsh_invocation(self, script: str) -> ShellInvocation:
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
        # Windows console utilities (ipconfig, chcp-sensitive tools) write
        # through WriteConsole; PowerShell redirects that output, but only if
        # the console encoding matches what the pipe consumer expects.  Force
        # the child's console and pipeline encodings to UTF-8 up front so
        # captured bytes decode cleanly at the boundary instead of arriving in
        # the OEM codepage (which ``errors="replace"`` would corrupt).
        wrapped = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
            "$OutputEncoding = [System.Text.UTF8Encoding]::new($false)\n"
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


__all__ = [
    "PowerShellDialect",
    "decode_windows_output",
    "WINDOWS_UNSUPPORTED_TOKENS",
    "WINDOWS_ALWAYS_UNSAFE_TOKENS",
    "is_unsafe_windows_command",
    "windows_wrapper_escalation_reason",
]

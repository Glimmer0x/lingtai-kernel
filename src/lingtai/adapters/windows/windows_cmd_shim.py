"""Trusted cmd.exe shim handling for .cmd/.bat tools on Windows.

Our shell dialect is PowerShell (pwsh), but tools such as ``npm.cmd``,
``npx.cmd`` and ``yarn.cmd`` invoked by the model still resolve through
``cmd.exe`` when pwsh calls them implicitly.  That exposes the command to
cmd.exe semantics (``%VAR%`` expansion, ``^`` escaping, no single-quote
quoting, AutoRun) that PowerShell users do not expect.

This module mirrors OpenClaw's ``src/process/windows-command.ts`` approach:

1. ``npm``/``npx`` (with or without a ``.cmd``/``.bat`` suffix) resolve to a
   direct ``node <npm-dir>/bin/npm-cli.js`` (or ``npx-cli.js``) invocation so
   the .cmd shim is bypassed entirely; otherwise
2. a first token that resolves to a ``.cmd``/``.bat`` on PATH is wrapped in a
   trusted ``cmd.exe /d /s /c <command line>`` invocation with the same
   ``windowsVerbatimArguments``-style single-command-string transport, and
   metacharacters that are unsafe under cmd.exe (``%``, backtick, ``^``,
   ``$var``) are rejected rather than silently reinterpreted.

The single command string is produced with ``subprocess.list2cmdline`` over
args that were first passed through :func:`escape_for_windows_cmd_exe`; the
result is passed to ``cmd.exe`` as one final argument, so Python's own
CreateProcess command-line quoting (``shell=False`` -> ``list2cmdline``) only
adds the outer quoting pair that ``cmd.exe /s`` strips.  Args containing an
embedded double quote are deliberately not shimmed (the caller falls back to
pwsh) because ``list2cmdline`` escapes quotes with backslashes, which cmd.exe
does not understand.

Output is read as UTF-8 with replacement errors; cmd.exe builtins writing in
the OEM codepage may be mojibake'd, which is the accepted trade-off for
capturing piped output (node-based tools write UTF-8).
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess

logger = logging.getLogger(__name__)

__all__ = [
    "build_cmd_exe_invocation",
    "escape_for_windows_cmd_exe",
    "is_cmd_bat_shim",
    "reject_unsafe_metachars",
    "resolve_cmd_bat_shim",
    "resolve_npm_argv",
    "split_simple_command",
    "try_cmd_shim_plan",
]

_CMD_BAT_SUFFIXES = (".cmd", ".bat")

# Characters that change meaning inside a cmd.exe command line even when the
# command is wrapped in a trusted ``/d /s /c`` invocation (OpenClaw's
# ``escapeForWindowsCmdExe`` rejection set).  ``%`` expands variables, ``&
# | < >`` are operators, and ``\r``/``\n`` break line parsing.
_UNSAFE_ESCAPE_RE = re.compile(r"[&|<>%\r\n]")

# Metacharacters rejected for the trusted cmd.exe shim path (stricter than
# :func:`escape_for_windows_cmd_exe`): ``%VAR%`` expands under cmd.exe, the
# backtick is PowerShell's escape character, ``^`` is cmd.exe's escape
# character, and ``$var``/``$(...)``/``${...}`` are PowerShell expansions that
# a .cmd shim would pass through verbatim instead.
_UNSAFE_SHIM_METACHAR_RE = re.compile(r"[%`^]|\$[A-Za-z_0-9][A-Za-z0-9_:]*|\$\(|\$\{")

# Characters that make a script require PowerShell semantics (pipelines,
# chains, redirection, script blocks, subexpressions, escape sequences) and
# therefore disqualify it from the conservative single-command shim path.
_SIMPLE_COMMAND_FORBIDDEN = set(";|&(){}<>`")

# PowerShell variable/subexpression forms that must not be re-interpreted by a
# .cmd shim: ``$name``, ``$name:qual``, ``$(...)``, ``${...}``.
_PS_VAR_RE = re.compile(r"\$[A-Za-z_0-9][A-Za-z0-9_:]*|\$\(|\$\{")


def is_cmd_bat_shim(token: str) -> bool:
    """Return whether ``token`` names a ``.cmd``/``.bat`` shim (case-insensitive)."""
    return token.casefold().endswith(_CMD_BAT_SUFFIXES)


def escape_for_windows_cmd_exe(arg: str) -> str:
    """Escape one argument for a cmd.exe command line (OpenClaw-compatible).

    Rejects ``& | < > %`` and ``\r``/``\n`` with :class:`ValueError` (they
    cannot be safely escaped), escapes ``^`` as ``^^``, and doubles embedded
    double quotes with surrounding quotes (cmd.exe has no backslash
    escaping).  Args with spaces are left for ``subprocess.list2cmdline`` to
    quote.
    """
    if _UNSAFE_ESCAPE_RE.search(arg):
        raise ValueError(
            f"cannot escape argument for cmd.exe: unsafe metacharacter in {arg!r}"
        )
    escaped = arg.replace("^", "^^")
    if '"' in escaped:
        # NOTE: on the trusted-shim calling path this branch (and the ``^``
        # branch above) is dead: ``reject_unsafe_metachars`` rejects ``^``
        # first, and ``split_simple_command`` refuses tokens containing ``"``.
        # They are kept so this remains a correct general-purpose cmd.exe
        # escaper; a future caller that reorders the checks would silently
        # change semantics.
        escaped = '"' + escaped.replace('"', '""') + '"'
    return escaped


def reject_unsafe_metachars(args: list[str]) -> None:
    """Reject metacharacters that are unsafe under the cmd.exe shim.

    Rejects ``%``, backtick, ``^``, and PowerShell ``$var``/``$(...)``/
    ``${...}`` forms in any argument with :class:`ValueError`.  These stay
    unsafe even inside double quotes: cmd.exe expands ``%VAR%`` and treats
    ``^`` as an escape, and a ``$var`` would silently lose its PowerShell
    meaning when handed to a .cmd shim.
    """
    for arg in args:
        match = _UNSAFE_SHIM_METACHAR_RE.search(arg)
        if match:
            raise ValueError(
                "refusing cmd.exe shim: unsafe metacharacter "
                f"{match.group(0)!r} in argument {arg!r}"
            )


def split_simple_command(script: str) -> list[str] | None:
    """Tokenize a single simple command, or return ``None``.

    A *simple command* is one bare command word plus whitespace-separated
    arguments with balanced single/double quotes.  PowerShell quoting rules
    are honored for the conservative subset: doubled quotes inside a quoted
    region (``"a""b"`` -> ``a"b``, ``'it''s'`` -> ``it's``) decode to a
    literal quote, and backtick escapes are rejected outright.

    Returns ``None`` (caller falls back to pwsh) for pipelines, chains,
    redirection, script blocks, subexpressions, backtick escapes, PowerShell
    variables, unbalanced quotes, or any argument that still contains an
    embedded double quote (``list2cmdline`` cannot round-trip those through
    cmd.exe).
    """
    script = script.strip()
    if not script:
        return None
    if any(char in _SIMPLE_COMMAND_FORBIDDEN for char in script):
        return None
    if _PS_VAR_RE.search(script):
        return None
    tokens: list[str] = []
    index = 0
    length = len(script)
    while index < length:
        while index < length and script[index].isspace():
            index += 1
        if index >= length:
            break
        token: list[str] = []
        quote: str | None = None
        while index < length:
            char = script[index]
            if quote is not None:
                if char == quote:
                    if index + 1 < length and script[index + 1] == quote:
                        token.append(quote)
                        index += 2
                        continue
                    quote = None
                    index += 1
                    continue
                token.append(char)
                index += 1
                continue
            if char in "\"'":
                quote = char
                index += 1
                continue
            if char.isspace():
                break
            token.append(char)
            index += 1
        if quote is not None:
            return None
        tokens.append("".join(token))
    if not tokens:
        return None
    if any('"' in token for token in tokens):
        return None
    return tokens


def _which(name: str, path: str | None) -> str | None:
    if path is not None:
        return shutil.which(name, path=path)
    return shutil.which(name)


def _default_cmd_exe() -> str:
    """Return the trusted cmd.exe path or a bare fallback name.

    Prefers ``%SystemRoot%\\System32\\cmd.exe`` when that file exists (the
    hardened path, independent of the ambient ``COMSPEC``); falls back to
    ``COMSPEC`` and finally a bare ``cmd.exe`` name so minimal environments
    and tests keep working.
    """
    system_root = os.environ.get("SystemRoot")
    if system_root:
        candidate = os.path.join(system_root, "System32", "cmd.exe")
        if os.path.isfile(candidate):
            return candidate
    return os.environ.get("COMSPEC") or "cmd.exe"


def resolve_cmd_bat_shim(token: str, *, path: str | None = None) -> str | None:
    """Resolve ``token`` to a ``.cmd``/``.bat`` path on PATH, or ``None``.

    Handles explicit ``.cmd``/``.bat`` suffixes and PATHEXT-style bare names
    (on Windows ``npm`` resolves through ``npm.cmd``).  Returns ``None`` when
    the token does not resolve to a cmd shim, so callers keep the pwsh path.
    """
    if is_cmd_bat_shim(token):
        return _which(token, path)
    resolved = _which(token, path)
    if resolved is not None and is_cmd_bat_shim(resolved):
        return resolved
    return None


def _find_npm_cli_js(base: str, path: str | None) -> str | None:
    """Locate ``<base>-cli.js`` (npm-cli.js / npx-cli.js) next to the shim.

    Standard npm layout is ``<prefix>/node_modules/npm/bin/npm-cli.js`` next
    to ``<prefix>/npm.cmd``; a flat ``<prefix>/npm-cli.js`` layout is also
    accepted.  Lookups try both the token's original case and its casefolded
    form so an uppercase ``NPM.CMD`` still resolves on case-sensitive
    filesystems.  Returns the first existing script path or ``None``.
    """
    bases = [base]
    folded = base.casefold()
    if folded != base:
        bases.append(folded)
    dirs: list[str] = []
    for candidate_base in bases:
        for candidate in (f"{candidate_base}.cmd", f"{candidate_base}.bat", candidate_base):
            hit = _which(candidate, path)
            if hit:
                directory = os.path.dirname(hit)
                if directory not in dirs:
                    dirs.append(directory)
    for directory in dirs:
        for candidate_base in bases:
            cli_name = f"{candidate_base}-cli.js"
            for candidate in (
                os.path.join(directory, "node_modules", "npm", "bin", cli_name),
                os.path.join(directory, cli_name),
            ):
                if os.path.isfile(candidate):
                    return candidate
    return None


def resolve_npm_argv(cmd: list[str], *, path: str | None = None) -> list[str] | None:
    """Resolve npm/npx (or ``npm.cmd``/``npx.cmd``) to a direct node invocation.

    Returns ``[node, <npm-dir>/bin/npm-cli.js|npx-cli.js, *rest]``, bypassing
    the .cmd shim and its cmd.exe semantics, or ``None`` when the first token
    is not npm/npx or the CLI script/node executable cannot be located.
    """
    if not cmd:
        return None
    first = cmd[0]
    base = first[:-4] if is_cmd_bat_shim(first) else first
    if base.casefold() not in {"npm", "npx"}:
        return None
    node = _which("node", path)
    if node is None:
        return None
    cli = _find_npm_cli_js(base, path)
    if cli is None:
        return None
    return [node, cli, *cmd[1:]]


def build_cmd_exe_invocation(
    args: list[str], *, cmd_exe: str | None = None,
) -> list[str]:
    """Build the trusted ``cmd.exe`` wrapper argv for ``args``.

    Returns ``[<cmd.exe>, /d, /s, /c, <list2cmdline>]``: the payload is a
    single command string (the ``windowsVerbatimArguments`` equivalent).
    With ``shell=False`` Python builds the CreateProcess command line with
    ``subprocess.list2cmdline``, so the only extra quoting around the payload
    is the outer pair that ``cmd.exe /s`` strips.  Each argument is first
    passed through :func:`escape_for_windows_cmd_exe` (``^`` escaping and
    ``""`` doubling); reject unsafe metachars with
    :func:`reject_unsafe_metachars` before calling this when the shim path is
    taken.
    """
    if not args:
        raise ValueError("cannot build a cmd.exe shim invocation for an empty command")
    escaped = [escape_for_windows_cmd_exe(arg) for arg in args]
    payload = subprocess.list2cmdline(escaped)
    return [cmd_exe or _default_cmd_exe(), "/d", "/s", "/c", payload]


def try_cmd_shim_plan(
    script: str, *, path: str | None = None,
) -> tuple[str, list[str]] | None:
    """Plan a trusted non-pwsh execution for a .cmd/.bat shim command.

    Returns ``("node", argv)`` for npm/npx (direct node invocation of the CLI
    JS, no cmd.exe involved), ``("cmd", argv)`` for other ``.cmd``/``.bat``
    shims wrapped in trusted ``cmd.exe /d /s /c``, or ``None`` when the script
    is not a single simple command whose first token resolves to a shim (the
    caller then keeps the normal pwsh path).  Raises :class:`ValueError` when
    the command is a shim but contains metacharacters unsafe under cmd.exe.
    """
    argv = split_simple_command(script)
    if not argv:
        # Falls back to pwsh: complex scripts and scripts containing
        # PowerShell variables (``$var``/``$(...)``) keep PowerShell
        # semantics.  A .cmd/.bat shim in that position then runs through the
        # *ambient* cmd.exe, so log it for diagnosis -- unlike unsafe
        # metachars on the shim path, which raise :class:`ValueError`.
        first = script.split(None, 1)[0] if script.strip() else ""
        if first and (
            is_cmd_bat_shim(first) or resolve_cmd_bat_shim(first, path=path)
        ):
            logger.debug(
                "cmd shim command %r not shimmed (falls back to pwsh -> "
                "ambient cmd.exe): %s",
                first,
                script,
            )
        return None
    npm_argv = resolve_npm_argv(argv, path=path)
    if npm_argv is not None:
        return ("node", npm_argv)
    if resolve_cmd_bat_shim(argv[0], path=path) is None:
        return None
    reject_unsafe_metachars(argv)
    return ("cmd", build_cmd_exe_invocation(argv))

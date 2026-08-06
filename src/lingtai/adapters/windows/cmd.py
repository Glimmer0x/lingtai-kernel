"""cmd.exe dialect adapter for the shell language Port.

Only reachable through the ShellKind classifier (``LINGTAI_SHELL=cmd``, an
init.json ``shell_kind`` override, or the last-resort Windows fallback when
neither ``pwsh`` nor Git Bash is discoverable).  Policy extraction is
conservative: tokens are normalized (caret escapes decoded, quotes stripped,
``,``/``;``/``=`` argument delimiters and ``(...)`` blocks split) so the
shipped deny-list cannot be bypassed with ``d^el``, ``"del"``, ``del,x.txt``
or an ``if ... (del ...)`` block, and any ``%``-expansion (which can smuggle
in separators and command names no static tokenizer can see) fails closed
with an ``__cmd_unsupported__`` marker that ``ShellManager`` refuses under a
configured policy.  Over-splitting only ever denies more, never less.
"""
from __future__ import annotations

import re

from lingtai.tools.bash._shell_dialect import (
    ShellDialect,
    ShellInvocation,
    ShellKind,
    make_invocation_for_kind,
)

# Emitted when the script contains ``%VAR%`` expansion: cmd.exe expands
# variables before parsing, so ``%comspec% /c del x`` or ``echo %PATH%``
# (with a hostile PATH) can introduce separators and command names the
# static extractor cannot see.  Mirrors the PowerShell ``__powershell_unsupported__``
# refusal behavior in ``ShellManager._validate_command``.
_UNSUPPORTED = "__cmd_unsupported__"


def extract_cmd_commands(script: str) -> tuple[str, ...]:
    """Extract command names across cmd.exe statement separators.

    cmd.exe separates statements with ``&`` / ``&&``, pipes with ``|``, and
    newlines; it also treats ``,`` ``;`` ``=`` as argument delimiters, ``^``
    as the escape character, accepts quoted command names, and groups
    ``if``/``for`` bodies in ``(...)`` blocks.  Each of those is normalized
    so the extracted first tokens are the names cmd.exe would actually
    invoke: ``del,x.txt``, ``del;x.txt``, ``d^el x.txt`` and ``"del" x.txt``
    all yield ``del``, and ``if 1==1 (del x)`` yields ``del`` as well.
    Any ``%`` in the script fails closed with the unsupported marker.
    """
    if "%" in script:
        return (_UNSUPPORTED,)
    commands: list[str] = []
    # Caret is cmd's escape character: ``d^el`` is ``del`` and ``^&`` is a
    # literal ampersand.  Decoding it can only over-split later (extra
    # tokens to check), never hide a command name.
    _extract_script(script.replace("^", ""), commands)
    return tuple(commands)


def _extract_script(text: str, commands: list[str]) -> None:
    """Walk *text* at one paren depth, splitting statements outside ``(...)``.

    ``&``/``|``/newline separate statements only at depth 0; ``(...)`` block
    contents are parsed recursively so ``if 1==1 (del x)`` yields ``del``
    (an unparenthesized scan would miss it).  A stray or unclosed paren is
    inert: cmd.exe would error before running anything inside it.
    """
    statement: list[str] = []
    block: list[str] = []
    depth = 0
    for char in text:
        if char == "(":
            if depth == 0:
                _extract_statement("".join(statement), commands)
                statement = []
                depth = 1
                continue
            depth += 1
            block.append(char)
        elif char == ")":
            if depth == 0:
                statement.append(char)  # stray close; cmd.exe errors
            elif depth == 1:
                depth = 0
                _extract_script("".join(block), commands)
                block = []
            else:
                depth -= 1
                block.append(char)
        elif depth > 0:
            block.append(char)
        elif char in "&|\n":
            _extract_statement("".join(statement), commands)
            statement = []
        else:
            statement.append(char)
    _extract_statement("".join(statement), commands)


def _extract_statement(text: str, commands: list[str]) -> None:
    """Extract the command name of one statement.

    ``,``/``;``/``=`` delimit arguments, not statements, so only the first
    chunk carries the command name; a quoted command name is unwrapped
    (``"del" x.txt`` invokes ``del``).
    """
    head = re.split(r"[,;=]", text, maxsplit=1)[0]
    tokens = head.strip().split()
    if tokens:
        commands.append(tokens[0].strip('"'))


class CmdDialect(ShellDialect):
    """cmd.exe invocation and policy extraction."""

    def extract_commands(self, script: str) -> tuple[str, ...]:
        return extract_cmd_commands(script)

    def make_invocation(self, script: str) -> ShellInvocation:
        # %COMSPEC% (usually cmd.exe) is always present on Windows; the
        # constructor defaults it so the classifier never has to probe.
        return make_invocation_for_kind(ShellKind.CMD, script)

    def state_key(self) -> str:
        return ShellKind.CMD.value

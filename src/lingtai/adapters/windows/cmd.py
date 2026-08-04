"""cmd.exe dialect adapter for the shell language Port.

Only reachable through the ShellKind classifier (``LINGTAI_SHELL=cmd``, an
init.json ``shell_kind`` override, or the last-resort Windows fallback when
neither ``pwsh`` nor Git Bash is discoverable).  Policy extraction is
intentionally conservative: over-splitting a quoted separator only makes an
allowlist stricter (fail-closed), never looser.
"""
from __future__ import annotations

import re

from lingtai.tools.bash._shell_dialect import (
    ShellDialect,
    ShellInvocation,
    ShellKind,
    make_invocation_for_kind,
)


def extract_cmd_commands(script: str) -> tuple[str, ...]:
    """Extract first tokens across cmd.exe statement separators.

    cmd.exe separates statements with ``&`` / ``&&`` and pipes with ``|``;
    there is no ``;`` statement separator.  Quote awareness is intentionally
    omitted - a ``&`` inside quotes is over-split, which can only deny more
    (never allow) under a configured policy.
    """
    commands: list[str] = []
    for part in re.split(r"&|\||\n", script):
        tokens = part.strip().split()
        if tokens:
            commands.append(tokens[0])
    return tuple(commands)


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

"""POSIX production adapter for the Bash-local shell dialect."""
from __future__ import annotations

from lingtai.tools.bash._shell_dialect import (
    ShellDialect,
    ShellInvocation,
    ShellKind,
    extract_posix_commands,
    make_invocation_for_kind,
)


class PosixBashDialect(ShellDialect):
    def extract_commands(self, script: str) -> tuple[str, ...]:
        return extract_posix_commands(script)

    def make_invocation(self, script: str) -> ShellInvocation:
        # POSIX keeps the historical subprocess ``shell=True`` form; the
        # None/None fields preserve subprocess's historical text decoding.
        return make_invocation_for_kind(ShellKind.POSIX, script)

    def state_key(self) -> str:
        return ShellKind.POSIX.value

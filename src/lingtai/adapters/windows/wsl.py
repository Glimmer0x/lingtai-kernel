"""WSL (Windows Subsystem for Linux) bash dialect adapter.

Opt-in via ``LINGTAI_SHELL=wsl`` (or an init.json ``shell_kind`` override) -
WSL is never auto-selected.  Commands run as POSIX Bash inside the default
Linux distribution through ``wsl.exe -e bash -lc``.
"""
from __future__ import annotations

import shutil

from lingtai.tools.bash._shell_dialect import (
    ShellDialect,
    ShellInvocation,
    ShellKind,
    extract_posix_commands,
    make_invocation_for_kind,
)


def discover_wsl() -> str | None:
    """Return the ``wsl.exe`` launcher, or ``None`` when WSL is unavailable."""
    return shutil.which("wsl")


class WslDialect(ShellDialect):
    """WSL bash: POSIX grammar executed inside a Linux distribution."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or discover_wsl()
        if not self._executable:
            raise FileNotFoundError(
                "WSL launcher 'wsl.exe' was not found; install WSL or set "
                "LINGTAI_SHELL=cmd to use another shell"
            )

    def extract_commands(self, script: str) -> tuple[str, ...]:
        return extract_posix_commands(script)

    def make_invocation(self, script: str) -> ShellInvocation:
        return make_invocation_for_kind(
            ShellKind.WSL, script, executable=self._executable,
        )

    def state_key(self) -> str:
        return ShellKind.WSL.value

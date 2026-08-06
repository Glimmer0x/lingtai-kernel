"""Git Bash dialect adapter for the shell language Port.

Git Bash (Git for Windows) speaks POSIX Bash grammar but needs an explicit
``bash -lc`` spawn form instead of the historical ``shell=True`` shortcut.
The classifier and the dialect share :func:`discover_git_bash` so the chosen
kind and the spawned executable always agree.
"""
from __future__ import annotations

import os
import shutil

from lingtai.tools.bash._shell_dialect import (
    ShellDialect,
    ShellInvocation,
    ShellKind,
    extract_posix_commands,
    make_invocation_for_kind,
)

# Well-known Git for Windows install roots (32-bit and 64-bit layouts).
_GIT_BASH_CANDIDATES = (
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
)


def discover_git_bash() -> str | None:
    """Return a runnable Git Bash ``bash.exe`` path, or ``None``.

    The PATH fallback is deliberately narrowed: on a WSL-enabled host,
    ``%SystemRoot%\\System32\\bash.exe`` (the WSL launcher) shadows ``bash``
    on PATH, and spawning it would silently run WSL bash while the
    classifier and durable state report ``gitbash``.  WSL is opt-in only
    (never auto-selected), so any ``bash.exe`` resolved under the Windows
    system directory is rejected and the caller falls back to cmd.exe.
    """
    for candidate in _GIT_BASH_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    resolved = shutil.which("bash")
    if resolved and _is_windows_system_bash(resolved):
        return None
    return resolved


def _is_windows_system_bash(path: str) -> bool:
    """True when *path* is the WSL ``bash.exe`` launcher, never Git Bash.

    ``%SystemRoot%\\System32\\bash.exe`` (and the SysWOW64 twin) is the WSL
    launcher that ships with Windows Subsystem for Linux.  String-level
    comparison (no ``os.path`` calls) keeps the check identical when unit
    tests run on non-Windows hosts with Windows-style paths.
    """
    return path.replace("/", "\\").lower().endswith(
        ("\\system32\\bash.exe", "\\syswow64\\bash.exe")
    )


class GitBashDialect(ShellDialect):
    """Bash-for-Windows: POSIX grammar with an explicit ``bash -lc`` spawn."""

    def __init__(self, executable: str | None = None) -> None:
        self._executable = executable or discover_git_bash()
        if not self._executable:
            raise FileNotFoundError(
                "Git Bash executable 'bash.exe' was not found; set "
                "LINGTAI_SHELL=cmd or LINGTAI_SHELL=wsl to use another shell"
            )

    def extract_commands(self, script: str) -> tuple[str, ...]:
        return extract_posix_commands(script)

    def make_invocation(self, script: str) -> ShellInvocation:
        return make_invocation_for_kind(
            ShellKind.GITBASH, script, executable=self._executable,
        )

    def state_key(self) -> str:
        return ShellKind.GITBASH.value

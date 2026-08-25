"""Pure process-command matchers for LingTai agent host forms."""
from __future__ import annotations

import ntpath
import os
import posixpath
import re


def _is_absolute_anywhere(path: str) -> bool:
    """True if ``path`` is absolute under POSIX or Windows path syntax.

    ``ps command=`` text can carry either OS's path shape regardless of the
    OS this matcher happens to run on (e.g. Windows-shaped test fixtures
    exercised on POSIX CI), so relative-vs-absolute must be judged
    syntactically rather than via ``os.path.isabs``, which only knows the
    host OS's own convention.
    """
    return posixpath.isabs(path) or ntpath.isabs(path)


def match_agent_run(cmdline: str, working_dir: str) -> str | None:
    """Return the launch form if ``cmdline`` is an agent run for ``working_dir``.

    The matcher is intentionally conservative for the console-script and legacy
    forms: ``lingtai-agent`` / ``lingtai`` must be the command itself or the
    basename of a path. The module form is separate because real launches look
    like ``<python> -m lingtai run <dir>``.

    Residual limitation: ``ps command=`` is a flat string, not the original argv
    vector. A non-LingTai process can still match if its argument text is shaped
    exactly like an absolute LingTai program path followed by ``run <dir>``.

    Program anchoring accepts both path separators: Windows process tables
    report ``C:\\...\\Scripts\\lingtai-agent.exe run <dir>`` with backslashes,
    and a backslash immediately before the program name is as much a path
    anchor there as ``/`` is on POSIX. ``os.path.normpath`` on each platform
    normalizes the trailing directory the same way for the equality check.

    Relative ``<dir>`` arguments are intentionally unsupported. Symlink
    aliases are resolved with ``realpath`` only when ``working_dir`` is
    absolute on the host OS; a foreign-OS-shaped path (e.g. a Windows
    ``C:\\...`` path observed while running on POSIX) falls back to plain
    ``normpath`` equality, since ``realpath`` would otherwise resolve it
    against the wrong filesystem convention.
    """
    host_absolute = os.path.isabs(working_dir)
    target = (
        os.path.realpath(os.path.normpath(working_dir))
        if host_absolute
        else os.path.normpath(working_dir)
    )
    for token, label, program_anchored in (
        (" -m lingtai run ", "module", False),
        ("lingtai-agent run ", "console", True),
        ("lingtai run ", "legacy", True),
    ):
        idx = cmdline.find(token)
        while idx != -1:
            if (not program_anchored) or idx == 0 or cmdline[idx - 1] in ("/", "\\"):
                tail = cmdline[idx + len(token):].strip()
                if tail and _is_absolute_anywhere(tail):
                    resolved = (
                        os.path.realpath(os.path.normpath(tail))
                        if host_absolute
                        else os.path.normpath(tail)
                    )
                    if resolved == target:
                        return label
            idx = cmdline.find(token, idx + 1)
    return None

def _unquote_exact(value: str) -> str | None:
    value = value.strip()
    if not value:
        return None
    if value[0] in ("\"", "'"):
        if len(value) < 2 or value[-1] != value[0]:
            return None
        value = value[1:-1]
    elif value[-1:] in ("\"", "'"):
        return None
    return value or None


def _is_windows_absolute(path: str) -> bool:
    """Recognize drive-rooted and UNC Windows paths, not root-relative ones."""

    drive, _tail = ntpath.splitdrive(path)
    return bool(drive) and ntpath.isabs(path)


def _resolve_candidate(value: str) -> str | None:
    """Normalize one absolute candidate with its own path flavor.

    Process-table fixtures may carry a Windows path while this matcher runs on
    POSIX (or vice versa). Only host-native paths go through ``realpath``; a
    foreign path uses its own lexical normalizer so ``..`` and case semantics
    are not interpreted by the wrong OS.
    """

    value = _unquote_exact(value)
    if value is None:
        return None
    if _is_windows_absolute(value):
        normalized = ntpath.normcase(ntpath.normpath(value))
        if os.name == "nt":
            normalized = ntpath.normcase(os.path.realpath(normalized))
        return normalized
    if posixpath.isabs(value):
        normalized = posixpath.normpath(value)
        if os.name != "nt":
            normalized = os.path.realpath(normalized)
        return normalized
    return None


_PYTHON_PROGRAM_RE = re.compile(
    r"python(?:w)?(?:\d+(?:\.\d+)*)?(?:\.exe)?\Z", re.IGNORECASE
)


def _is_python_program(program: str) -> bool:
    basename = ntpath.basename(posixpath.basename(program))
    return _PYTHON_PROGRAM_RE.fullmatch(basename) is not None


def _exact_agent_dir_value(rest: str, prefix: str) -> str | None:
    if not rest.startswith(prefix):
        return None
    tail = rest[len(prefix) :]
    if tail.startswith("="):
        return tail[1:]
    if tail[:1].isspace():
        return tail.strip()
    return None


def _split_leading_program(cmdline: str) -> tuple[str, str] | None:
    """Split one start-anchored executable token from flat process text."""

    command = cmdline.strip()
    if not command:
        return None
    if command[0] in ("\"", "'"):
        quote = command[0]
        end = command.find(quote, 1)
        if end == -1:
            return None
        program = command[1:end]
        rest = command[end + 1 :].strip()
    else:
        parts = command.split(None, 1)
        program = parts[0]
        rest = parts[1].strip() if len(parts) == 2 else ""
    return program, rest


def match_agent_acp(cmdline: str, working_dir: str) -> str | None:
    """Return the exact local ACP launch form for ``working_dir``.

    Module launches retain their interpreter prefix. Console/legacy launches use
    a start-anchored executable grammar so quoted Windows paths and the installed
    ``lingtai-agent.exe`` form are recognized without matching argument-position
    lookalikes, wrappers, suffix executables, or trailing options.
    """

    target = _resolve_candidate(working_dir)
    if target is None:
        return None

    split = _split_leading_program(cmdline)
    if split is None:
        return None
    program, rest = split

    if _is_python_program(program):
        tail = _exact_agent_dir_value(rest, "-m lingtai acp --agent-dir")
        candidate = _resolve_candidate(tail) if tail is not None else None
        return "module" if candidate == target else None

    basename = ntpath.basename(posixpath.basename(program))
    if basename in ("lingtai-agent", "lingtai"):
        label = "console" if basename == "lingtai-agent" else "legacy"
    elif basename.casefold() in ("lingtai-agent.exe", "lingtai.exe"):
        label = "console" if basename.casefold() == "lingtai-agent.exe" else "legacy"
    else:
        return None

    tail = _exact_agent_dir_value(rest, "acp --agent-dir")
    candidate = _resolve_candidate(tail) if tail is not None else None
    return label if candidate == target else None

"""Output hygiene at the shell-tool boundary.

Raw terminal output frequently carries ANSI/CSI color and cursor sequences,
C0/C1 control bytes (bell, backspace, OSC title sequences, DEL), and
shell-startup noise lines (``bash: no job control in this shell``,
``warning: ...`` banners). Left verbatim, these pollute tool results, waste
context window, and can confuse downstream parsers that expect plain text.

This module provides the small, dependency-free helpers the shell tool
applies before returning output:

- :func:`strip_ansi` -- remove ANSI/CSI escape sequences (colors, cursor
  moves, OSC titles, single-char ESC sequences).
- :func:`escape_controls` -- escape C0/C1 control characters as ``\\xNN``
  while keeping ``\\t``, ``\\n`` and ``\\r`` readable.
- :func:`strip_shell_startup_noise` -- drop known startup-warning lines from
  the head of a line list (Hermes ``_clean_shell_noise`` semantics: substring
  noise list plus a ``^warning: `` banner pattern).
- :func:`truncate_output` -- cap output with an explicit truncation marker.

The shell tool composes these in :func:`sanitize_output`, applied to both
stdout and stderr before a result is returned.
"""
from __future__ import annotations

import re

__all__ = [
    "escape_controls",
    "sanitize_output",
    "strip_ansi",
    "strip_shell_startup_noise",
    "truncate_output",
]

# ANSI/CSI escape sequences.  Three shapes:
#   CSI        ESC [ params... intermediates... final-byte  (colors, cursor moves)
#   OSC        ESC ] ... BEL (0x07) or ESC \\               (window title, hyperlinks)
#   single-ESC ESC + one byte (e.g. ESC c reset, ESC 7 save cursor)
# Character-set designations (ESC ( B / ESC ) 0) are folded in via the [()]
# alternative.  Dangling or malformed ESC bytes are left in place;
# escape_controls then renders them (and any C1 control bytes) as \\xNN.
_ANSI_ESCAPE_RE = re.compile(
    r"""
    \x1b\[[0-9;:?]*[ -/]*[@-~]            # CSI
    | \x1b\][^\x07\x1b]*(?:\x07|\x1b\\)  # OSC, terminated by BEL or ESC \\
    | \x1b[()][0-9A-Za-z]                 # character-set designation
    | \x1b[@-Z\\-_]                       # other single-char ESC sequences
    """,
    re.VERBOSE,
)

# C0 (0x00-0x1F minus tab/LF/CR, plus DEL 0x7F) and C1 (0x80-0x9F) controls.
_C0_C1_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Shell-startup noise substrings, mirroring Hermes ProcessRegistry.
_SHELL_NOISE_SUBSTRINGS = (
    "bash: cannot set terminal process group",
    "bash: no job control in this shell",
    "no job control in this shell",
    "cannot set terminal process group",
    "tcsetattr: Inappropriate ioctl for device",
)

# Leading banner pattern (bash warning lines, toolchain startup warnings).
_STARTUP_NOISE_RE = re.compile(r"^warning: ")


_TRUNCATION_MARKER = "... [output truncated at {max_chars} chars]"


# ---------------------------------------------------------------------------
# Individual helpers
# ---------------------------------------------------------------------------

def strip_ansi(text: str) -> str:
    """Remove ANSI/CSI escape sequences from *text*.

    Strips CSI color/cursor sequences, OSC title sequences, character-set
    designations, and single-char ESC sequences.  Plain text passes through
    unchanged; dangling ESC bytes are left for :func:`escape_controls`.
    """
    return _ANSI_ESCAPE_RE.sub("", text)


def escape_controls(text: str) -> str:
    """Escape C0/C1 control characters in *text* as ``\\xNN``.

    Tab (``\\t``), newline (``\\n``) and carriage return (``\\r``) are kept
    as-is; every other C0 control (including DEL) and every C1 control
    (``0x80``-``0x9F``) is rendered as an explicit ``\\xNN`` escape so no
    invisible or terminal-interpreting byte survives into a tool result.
    """
    return _C0_C1_CONTROL_RE.sub(lambda m: f"\\x{ord(m.group(0)):02x}", text)


def strip_shell_startup_noise(lines: list[str]) -> list[str]:
    """Drop known shell-startup noise lines from the head of *lines*.

    Only the *head* is examined (Hermes ``_clean_shell_noise`` semantics): a
    line is dropped while it is the first remaining line and either matches
    ``^warning: `` or contains a known startup-noise substring (bash job
    control / tcsetattr messages).  Genuine output lines that merely contain
    such text later in the stream are preserved.
    """
    result = list(lines)
    while result and _is_startup_noise_line(result[0]):
        result.pop(0)
    return result


def truncate_output(text: str, max_chars: int = 100_000) -> str:
    """Cap *text* at *max_chars* characters with an explicit marker.

    Outputs at or under the cap are returned unchanged.  Longer outputs are
    cut to ``max_chars`` characters and suffixed with a newline and
    ``... [output truncated at N chars]`` so the truncation is explicit and
    unambiguous to the model.
    """
    if len(text) <= max_chars:
        return text
    marker = _TRUNCATION_MARKER.format(max_chars=max_chars)
    return text[:max_chars] + "\n" + marker


# ---------------------------------------------------------------------------
# Composed pipeline
# ---------------------------------------------------------------------------

def sanitize_output(text: str, max_chars: int = 100_000) -> str:
    """Apply the full output-hygiene pipeline to one output stream.

    Order: strip ANSI/CSI, escape remaining C0/C1 controls, drop shell
    startup noise from the head, then cap with the truncation marker.
    Stripping ANSI first lets the ``^warning: `` head pattern match banner
    lines that arrived wrapped in color codes.
    """
    text = strip_ansi(text)
    text = escape_controls(text)
    text = "\n".join(strip_shell_startup_noise(text.split("\n")))
    return truncate_output(text, max_chars=max_chars)


def _is_startup_noise_line(line: str) -> bool:
    """Return whether a single head line is startup noise."""
    if _STARTUP_NOISE_RE.match(line):
        return True
    return any(noise in line for noise in _SHELL_NOISE_SUBSTRINGS)

"""Output hygiene at the shell-tool boundary.

Raw terminal output frequently carries ANSI/CSI color and cursor sequences,
C0/C1 control bytes (bell, backspace, OSC title sequences, DEL), and
shell-startup noise lines (``bash: no job control in this shell``,
``tcsetattr: ...``). Left verbatim, these pollute tool results, waste
context window, and can confuse downstream parsers that expect plain text.

This module provides the small, dependency-free helpers the shell tool
applies before returning output:

- :func:`strip_ansi` -- remove ANSI/CSI escape sequences (colors, cursor
  moves, OSC titles, single-char ESC sequences).
- :func:`escape_controls` -- escape C0/C1 control characters as ``\\xNN``
  while keeping ``\\t``, ``\\n`` and ``\\r`` readable.
- :func:`strip_shell_startup_noise` -- drop known shell-init noise lines
  (``bash: no job control in this shell``, ``tcsetattr: ...``) from the head
  of a line list, using only specific line-anchored patterns so genuine
  ``warning:`` command output (git checkout/add on Windows) is never
  silently deleted.
- :func:`truncate_output` -- cap output with an explicit truncation marker
  that reports the original length.

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
    | \x1b[0-9@-Z\\^_a-z{|}~]              # single-char ESC (incl. ESC 7/8, ESC c reset)
    """,
    re.VERBOSE,
)

# C0 (0x00-0x1F minus tab/LF/CR, plus DEL 0x7F) and C1 (0x80-0x9F) controls.
_C0_C1_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Shell-startup noise lines, mirrored from Hermes ProcessRegistry, anchored to
# the *start* of a head line.  Anchoring (and dropping the generic
# "^warning: " banner pattern) ensures genuine command output survives:
# git checkout/add stderr on Windows routinely begins with "warning: LF will
# be replaced by CRLF...", and `grep -r "no job control in this shell" .`
# output lines start with a filename, not the search string.
_STARTUP_NOISE_LINE_RE = re.compile(
    r"^(?:"
    r"bash: cannot set terminal process group"
    r"|bash: no job control in this shell"
    r"|no job control in this shell"
    r"|cannot set terminal process group"
    r"|tcsetattr: Inappropriate ioctl for device"
    r")"
)


# The truncation marker (``... (truncated, N chars total)``) is built inline
# in truncate_output so it can report the original length.


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
    """Drop known shell-init noise lines from the head of *lines*.

    Only the *head* is examined (Hermes ``_clean_shell_noise`` semantics): a
    line is dropped while it is the first remaining line and matches a
    specific, line-anchored noise pattern (``bash: no job control in this
    shell``, ``tcsetattr: Inappropriate ioctl for device``, ...).  Generic
    ``warning:`` head lines are *not* dropped -- they are usually genuine
    command output (git checkout/add on Windows) -- and lines merely
    *containing* a noise substring later in the stream are preserved.
    """
    result = list(lines)
    while result and _is_startup_noise_line(result[0]):
        result.pop(0)
    return result


def truncate_output(
    text: str, max_chars: int = 100_000, *, total_chars: int | None = None
) -> str:
    """Cap *text* at *max_chars* characters with an explicit marker.

    Outputs at or under the cap are returned unchanged.  Longer outputs are
    cut to ``max_chars`` characters and suffixed with a newline and
    ``... (truncated, N chars total)`` where *N* is the *original* length
    (``total_chars`` when the caller passes a pre-capped slice, otherwise
    ``len(text)``) so the model can tell whether it lost 1 KB or 500 MB.
    """
    if total_chars is None:
        total_chars = len(text)
    if len(text) <= max_chars and total_chars <= max_chars:
        return text
    return text[:max_chars] + f"\n... (truncated, {total_chars} chars total)"


# ---------------------------------------------------------------------------
# Composed pipeline
# ---------------------------------------------------------------------------

# Pre-cap bound for sanitize_output: escape_controls can expand each control
# byte to four chars, so before running the regex passes the input is sliced
# to max_chars * 4 plus slack for head noise lines and the marker.  This
# restores the old work bound (pre-PR code sliced to _max_output immediately)
# for async log files that can be hundreds of MB or binary.
_PRE_CAP_FACTOR = 4
_PRE_CAP_SLACK = 4096


def sanitize_output(text: str, max_chars: int = 100_000) -> str:
    """Apply the full output-hygiene pipeline to one output stream.

    Order: strip ANSI/CSI, escape remaining C0/C1 controls, drop shell
    startup noise from the head, then cap with the truncation marker.  The
    input is pre-capped to ``max_chars * 4 + slack`` before the regex passes
    so pathological streams never cost multiple full-size passes, and the
    marker reports the *original* length (captured before the pre-cap).
    """
    original_len = len(text)
    pre_cap = max_chars * _PRE_CAP_FACTOR + _PRE_CAP_SLACK
    if original_len > pre_cap:
        text = text[:pre_cap]
    text = strip_ansi(text)
    text = escape_controls(text)
    text = "\n".join(strip_shell_startup_noise(text.split("\n")))
    return truncate_output(text, max_chars=max_chars, total_chars=original_len)


def _is_startup_noise_line(line: str) -> bool:
    """Return whether a single head line is startup noise (line-anchored)."""
    return _STARTUP_NOISE_LINE_RE.match(line) is not None

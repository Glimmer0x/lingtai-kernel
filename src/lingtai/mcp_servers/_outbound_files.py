"""Shared outbound-file containment policy for MCP send tools.

The IMAP ``attachments``, Telegram ``media.path`` and WeChat ``media_path``
tool fields accept agent-supplied local file paths that are then read and
uploaded/sent to an external service.  Without containment, a
prompt-injection or an over-broad tool call can exfiltrate arbitrary local
files (``~/.ssh/id_rsa``, agent ``.secrets/*``, ...) to an outside
recipient/chat.

This module is the single enforcement point: relative paths resolve against
the agent working directory, and anything that, after symlink/``..``
resolution, lies outside the working directory is rejected.
"""
from __future__ import annotations

from pathlib import Path


class OutboundFileError(ValueError):
    """Raised when a tool-supplied path is not allowed as an outbound file."""


def resolve_outbound_file(raw: str | Path, working_dir: Path) -> Path:
    """Resolve ``raw`` against ``working_dir`` and enforce containment.

    - Relative paths resolve against ``working_dir``.
    - The result is fully resolved (``..`` and symlinks followed) and must be
      inside ``working_dir``; otherwise :class:`OutboundFileError` is raised.

    The caller is still responsible for checking ``is_file()`` before use.
    """
    wd = working_dir.resolve()
    p = Path(raw)
    if not p.is_absolute():
        p = wd / p
    p = p.resolve()
    if not p.is_relative_to(wd):
        raise OutboundFileError(
            f"refusing outbound file outside working directory: {raw}"
        )
    return p

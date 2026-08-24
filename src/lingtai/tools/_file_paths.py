"""Shared path helpers for built-in file tool wrappers."""
from __future__ import annotations

from pathlib import Path


def resolve_workdir_path(workdir: Path, path: str | Path) -> str | Path:
    """Resolve relative tool paths against *workdir*.

    Absolute paths pass through unchanged to preserve the file tools' historical
    string/path behavior and error messages.  Callers pass the narrow workdir
    host port's current path, never a live Agent.
    """
    if not Path(path).is_absolute():
        return str(workdir / path)
    return path

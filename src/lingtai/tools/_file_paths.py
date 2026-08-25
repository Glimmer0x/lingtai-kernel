"""Shared path helpers for built-in file tool wrappers."""
from __future__ import annotations

from pathlib import Path

from lingtai.kernel.execution_workspace import (
    current_execution_workspace,
    resolve_execution_path,
)


def resolve_workdir_path(workdir: Path, path: str | Path) -> str | Path:
    """Resolve relative tool paths against *workdir*.

    Absolute paths pass through unchanged to preserve the file tools' historical
    string/path behavior and error messages.  Callers pass the narrow workdir
    host port's current path, never a live Agent.
    """
    if current_execution_workspace() is None:
        if not Path(path).is_absolute():
            return str(workdir / path)
        return path
    return str(resolve_execution_path(path, fallback_root=workdir))

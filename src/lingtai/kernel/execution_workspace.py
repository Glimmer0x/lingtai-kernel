"""Immutable, task-local execution workspace for execution-facing tools."""
from __future__ import annotations

from contextvars import Context, ContextVar, Token, copy_context
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ExecutionWorkspace:
    """Canonical root applied to one correlated turn's execution operations."""

    root: Path

    def __post_init__(self) -> None:
        try:
            root = Path(self.root).expanduser().resolve(strict=True)
        except (TypeError, OSError, RuntimeError) as exc:
            raise ValueError("execution workspace must be an existing directory") from exc
        if not root.is_dir():
            raise ValueError("execution workspace must be an existing directory")
        object.__setattr__(self, "root", root)


_CURRENT: ContextVar[ExecutionWorkspace | None] = ContextVar(
    "lingtai_execution_workspace", default=None
)


def current_execution_workspace() -> ExecutionWorkspace | None:
    return _CURRENT.get()


def bind_execution_workspace(
    workspace: ExecutionWorkspace | None,
) -> Token[ExecutionWorkspace | None]:
    return _CURRENT.set(workspace)


def reset_execution_workspace(token: Token[ExecutionWorkspace | None]) -> None:
    _CURRENT.reset(token)


def clear_execution_workspace() -> None:
    """Clear the current thread's scope at a terminal turn-loop boundary."""
    _CURRENT.set(None)


def copy_execution_context() -> Context:
    """Capture the submitting thread's ContextVar state for worker dispatch."""
    return copy_context()


def resolve_execution_path(path: str | Path, *, fallback_root: str | Path) -> Path:
    """Resolve a tool path and enforce the active execution-workspace boundary."""

    workspace = current_execution_workspace()
    if workspace is None:
        candidate = Path(path).expanduser()
        return candidate if candidate.is_absolute() else Path(fallback_root) / candidate

    root = workspace.root
    candidate = Path(path).expanduser()
    resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes execution workspace: {path}") from exc
    return resolved


__all__ = [
    "ExecutionWorkspace",
    "bind_execution_workspace",
    "clear_execution_workspace",
    "current_execution_workspace",
    "reset_execution_workspace",
    "resolve_execution_path",
    "copy_execution_context",
]

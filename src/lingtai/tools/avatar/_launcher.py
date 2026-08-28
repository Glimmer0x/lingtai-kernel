"""Avatar-local process launch Port."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


# This is deliberately a restrictive boot marker, never an authority bearer:
# a child that forges it can only make its own nested derived launch fail closed.
DERIVED_AVATAR_EXECUTION_ENV = "LINGTAI_DERIVED_AVATAR_EXECUTION"


@dataclass(frozen=True)
class AvatarLaunchRequest:
    """The complete launch input; cwd is inherited and env overrides are explicit."""

    argv: tuple[str, ...]
    stderr_path: Path
    environment: Mapping[str, str] | None = None


@dataclass(frozen=True)
class AvatarLaunchReceipt:
    """PID plus an opaque adapter-owned process handle."""

    pid: int
    handle: object


class AvatarLauncherPort(Protocol):
    def launch(self, request: AvatarLaunchRequest) -> AvatarLaunchReceipt: ...
    def poll(self, handle: object) -> int | None: ...
    def terminate(self, handle: object) -> None:
        """Request adapter-native termination; not a process-tree operation."""
    def force_terminate(self, handle: object) -> None:
        """Forcefully terminate one owned process; never a tree kill."""
    def release(self, handle: object) -> None:
        """Best-effort, non-raising release that never terminates a live process."""

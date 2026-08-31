"""Avatar-local process launch Port."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol


# This is deliberately a restrictive boot marker, never an authority bearer:
# a child that forges it can only make its own nested derived launch fail closed.
DERIVED_AVATAR_EXECUTION_ENV = "LINGTAI_DERIVED_AVATAR_EXECUTION"

# This durable marker makes derived status an attribute of the avatar working
# directory, not of one particular launcher invocation.  Its mere presence is
# restrictive: malformed content or an unexpected replacement must never make
# a previously-derived child fall back to legacy admission behavior.
# This is deliberately outside the child-managed ``system/`` namespace.  The
# marker is a restart restriction, not ordinary agent state that a capability
# may clean up while doing its own maintenance.
DERIVED_AVATAR_STATE_RELATIVE_PATH = Path(".lingtai-derived-child.json")
DERIVED_AVATAR_STATE = {
    "schema_version": 1,
    "requires_derived_launch_admission": True,
}


def derived_avatar_state_path(working_dir: Path) -> Path:
    """Return the durable, restrictive state location for one avatar child."""
    return working_dir / DERIVED_AVATAR_STATE_RELATIVE_PATH


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

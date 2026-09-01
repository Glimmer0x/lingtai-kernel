"""Avatar-local process launch Port."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
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
# Derived children created before the marker moved out of ``system/`` retain
# their restriction at this location.  It is read-only compatibility state:
# new children are always written at ``DERIVED_AVATAR_STATE_RELATIVE_PATH``.
LEGACY_DERIVED_AVATAR_STATE_RELATIVE_PATH = Path("system") / "derived_child.json"
DERIVED_AVATAR_STATE = {
    "schema_version": 1,
    "requires_derived_launch_admission": True,
}


class DerivedAvatarState(str, Enum):
    """The durable marker's observable state without collapsing I/O failure."""

    PRESENT = "present"
    ABSENT = "absent"
    UNKNOWN = "unknown"


def derived_avatar_state_path(working_dir: Path) -> Path:
    """Return the durable, restrictive state location for one avatar child."""
    return working_dir / DERIVED_AVATAR_STATE_RELATIVE_PATH


def legacy_derived_avatar_state_path(working_dir: Path) -> Path:
    """Return the read-only restrictive marker location used by older children."""
    return working_dir / LEGACY_DERIVED_AVATAR_STATE_RELATIVE_PATH


def probe_derived_avatar_state(working_dir: Path) -> DerivedAvatarState:
    """Classify current and legacy markers without treating I/O failure as absence.

    Only ``FileNotFoundError`` for *both* locations proves that the durable
    restriction was removed.  Other filesystem failures stay observable to the
    caller as ``UNKNOWN`` so each caller can apply its own conservative policy
    without duplicating the lossy ``exists()`` predicate.
    """
    for state_path in (
        derived_avatar_state_path(working_dir),
        legacy_derived_avatar_state_path(working_dir),
    ):
        try:
            state_path.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return DerivedAvatarState.UNKNOWN
        return DerivedAvatarState.PRESENT
    return DerivedAvatarState.ABSENT


@dataclass(frozen=True)
class AvatarLaunchRequest:
    """The complete launch input; cwd is inherited and env overrides are explicit.

    ``authority_lease`` is opaque adapter-owned state.  Avatar Core carries it
    from one approved derived-launch decision to its launcher Port, but never
    inspects it as an FD or treats it as authority itself.
    """

    argv: tuple[str, ...]
    stderr_path: Path
    environment: Mapping[str, str] | None = None
    authority_lease: object | None = None


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

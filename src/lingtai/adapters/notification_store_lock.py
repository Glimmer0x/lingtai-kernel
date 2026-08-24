"""Platform selection and same-process Store resource serialization."""

from __future__ import annotations

import contextlib
import os
import threading
from contextlib import ExitStack
from pathlib import Path
from typing import Iterable

from lingtai.kernel.notification_store._mutation_lock import (
    NotificationMutationLockPort,
    notification_mutation_lock_path,
)

_PROCESS_LOCKS_GUARD = threading.Lock()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}


def _same_process_lock(notification_dir: Path, scope: str) -> threading.RLock:
    """Return the process-wide guard for one native resource-lock path.

    POSIX `flock` ownership is per open file description, so independently
    constructed Store adapters in one process still need this guard.  It is
    keyed by the canonical lock path, not by a Store instance.
    """
    key = str(notification_mutation_lock_path(notification_dir, scope).resolve(strict=False))
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


@contextlib.contextmanager
def exclusive_notification_mutation(
    mutation_lock: NotificationMutationLockPort,
    notification_dir: Path,
    scopes: str | Iterable[str],
):
    """Hold deduplicated resource locks in deterministic order."""
    requested = [scopes] if isinstance(scopes, str) else list(scopes)
    ordered = sorted(set(requested))
    if not ordered:
        raise ValueError("at least one notification mutation lock scope is required")
    with ExitStack() as stack:
        for scope in ordered:
            stack.enter_context(_same_process_lock(notification_dir, scope))
            stack.enter_context(mutation_lock.exclusive(notification_dir, scope))
        yield


def select_notification_store_lock() -> NotificationMutationLockPort:
    """Return the native cross-process lock for this platform."""
    if os.name == "posix":
        from .posix.notification_store_lock import PosixNotificationStoreLockAdapter

        return PosixNotificationStoreLockAdapter()
    if os.name == "nt":
        from .windows.notification_store_lock import WindowsNotificationStoreLockAdapter

        return WindowsNotificationStoreLockAdapter()
    raise NotImplementedError(
        f"notification Store mutation locking is unsupported on {os.name!r}"
    )

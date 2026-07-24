"""POSIX cross-process mutation lock for the Notification Store."""

from __future__ import annotations

import contextlib
import fcntl
from pathlib import Path

_LOCK_FILE = ".store.lock"


class PosixNotificationStoreLockAdapter:
    """Advisory ``flock`` held for one complete Store mutation."""

    @contextlib.contextmanager
    def exclusive(self, notification_dir: Path):
        notification_dir.mkdir(parents=True, exist_ok=True)
        handle = open(notification_dir / _LOCK_FILE, "a+b")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

"""POSIX resource locks with a one-release legacy `.store.lock` bridge."""

from __future__ import annotations

import contextlib
import fcntl
from pathlib import Path

from lingtai.kernel.notification_store._mutation_lock import notification_mutation_lock_path

_LEGACY_LOCK_FILE = ".store.lock"


class PosixNotificationStoreLockAdapter:
    """Scope-local exclusive flock plus shared lock against legacy writers.

    The shared legacy acquisition is intentionally retained for exactly one
    compatibility release: an old global exclusive holder excludes every new
    mutation, while two new unrelated resource mutations still share it.
    """

    @contextlib.contextmanager
    def exclusive(self, notification_dir: Path, scope: str):
        notification_dir.mkdir(parents=True, exist_ok=True)
        legacy_handle = open(notification_dir / _LEGACY_LOCK_FILE, "a+b")
        scoped_path = notification_mutation_lock_path(notification_dir, scope)
        scoped_path.parent.mkdir(parents=True, exist_ok=True)
        scoped_handle = open(scoped_path, "a+b")
        legacy_locked = False
        scoped_locked = False
        try:
            fcntl.flock(legacy_handle.fileno(), fcntl.LOCK_SH)
            legacy_locked = True
            fcntl.flock(scoped_handle.fileno(), fcntl.LOCK_EX)
            scoped_locked = True
            yield
        finally:
            try:
                if scoped_locked:
                    fcntl.flock(scoped_handle.fileno(), fcntl.LOCK_UN)
            finally:
                try:
                    if legacy_locked:
                        fcntl.flock(legacy_handle.fileno(), fcntl.LOCK_UN)
                finally:
                    scoped_handle.close()
                    legacy_handle.close()

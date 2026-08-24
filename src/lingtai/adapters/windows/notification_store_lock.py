"""Windows resource locks for the Notification Store."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

from lingtai.kernel.notification_store._mutation_lock import notification_mutation_lock_path


class WindowsNotificationStoreLockAdapter:
    """Byte-range lock held for one scoped Store mutation.

    Windows `msvcrt.locking` cannot express the POSIX bridge's shared lock.
    Upgrades therefore require a documented quiesced cutover: do not run an old
    `.store.lock` writer concurrently with this adapter.  The adapter does not
    pretend that an exclusive legacy lock would preserve scoped concurrency.
    """

    requires_quiesced_legacy_cutover = True

    @contextlib.contextmanager
    def exclusive(self, notification_dir: Path, scope: str):
        if __import__("os").name != "nt":
            raise OSError("Windows notification Store lock requires Windows")
        import msvcrt

        lock_path = notification_mutation_lock_path(notification_dir, scope)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_path, "a+b")
        locked = False
        try:
            if handle.seek(0, 2) == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    locked = True
                    break
                except OSError as exc:
                    if getattr(exc, "winerror", None) != 33 and exc.errno not in {13, 36}:
                        raise
                    time.sleep(0.01)
            yield
        finally:
            try:
                if locked:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            finally:
                handle.close()

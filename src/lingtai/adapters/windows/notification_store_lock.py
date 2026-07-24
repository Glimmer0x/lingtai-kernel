"""Windows cross-process mutation lock for the Notification Store."""

from __future__ import annotations

import contextlib
import time
from pathlib import Path

_LOCK_FILE = ".store.lock"


class WindowsNotificationStoreLockAdapter:
    """Byte-range lock held for one complete Store mutation."""

    @contextlib.contextmanager
    def exclusive(self, notification_dir: Path):
        if __import__("os").name != "nt":
            raise OSError("Windows notification Store lock requires Windows")
        import msvcrt

        notification_dir.mkdir(parents=True, exist_ok=True)
        handle = open(notification_dir / _LOCK_FILE, "a+b")
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
                    if getattr(exc, "winerror", None) != 33 and exc.errno not in {
                        13,
                        36,
                    }:
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

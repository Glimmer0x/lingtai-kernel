"""Cross-process mutation lock Port for the Notification Store."""

from __future__ import annotations

from contextlib import AbstractContextManager
from pathlib import Path
from typing import Protocol


class NotificationMutationLockPort(Protocol):
    """Serialize Store mutations across independently composed processes."""

    def exclusive(self, notification_dir: Path) -> AbstractContextManager[None]: ...

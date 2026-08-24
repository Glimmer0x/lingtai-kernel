"""Store-private resource-scoped cross-process lock vocabulary.

Lock scope names never become notification state.  They are mapped to bounded,
collision-resistant paths solely by the filesystem adapters.
"""

from __future__ import annotations

import hashlib
import re
from contextlib import AbstractContextManager
from pathlib import Path, PurePath
from typing import Protocol

_LOCK_DIRECTORY = ".locks"
_SAFE_SCOPE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_SCOPE_LABEL_MAX = 48


def channel_mutation_scope(channel: str) -> str:
    """Return the Store-private serialization scope for a channel mirror."""
    if not isinstance(channel, str) or not channel:
        raise ValueError("notification channel lock scope requires a non-empty channel")
    return f"channel:{channel}"


def daemon_run_mutation_scope(daemon_id: str) -> str:
    """Return the Store-private serialization scope for one daemon mini-file."""
    if not isinstance(daemon_id, str) or not daemon_id:
        raise ValueError("daemon run lock scope requires a non-empty daemon id")
    return f"daemon-run:{daemon_id}"


def resource_mutation_scope(resource: str) -> str:
    """Return the Store-private serialization scope for a non-channel resource."""
    if not isinstance(resource, str) or not resource:
        raise ValueError("notification resource lock scope requires a non-empty name")
    return f"resource:{resource}"


def notification_mutation_lock_path(notification_dir: Path, scope: str) -> Path:
    """Map one logical scope to a bounded, collision-resistant lock filename."""
    if not isinstance(scope, str) or not scope:
        raise ValueError("notification mutation lock scope must be a non-empty string")
    label = _SAFE_SCOPE_RE.sub("-", scope).strip("-._")[:_SCOPE_LABEL_MAX] or "scope"
    digest = hashlib.sha256(scope.encode("utf-8")).hexdigest()[:20]
    base = notification_dir if isinstance(notification_dir, PurePath) else Path(notification_dir)
    return base / _LOCK_DIRECTORY / f"{label}-{digest}.lock"


class NotificationMutationLockPort(Protocol):
    """Serialize one Store resource across independently composed processes."""

    def exclusive(
        self, notification_dir: Path, scope: str
    ) -> AbstractContextManager[None]: ...

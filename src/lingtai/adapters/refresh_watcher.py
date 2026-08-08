"""Outer platform selector for the RefreshWatcher capability.

Composition roots call this selector instead of constructing a platform
adapter directly.  This slice ships production POSIX and Windows adapters;
other unsupported platforms fail before importing either one rather than
receiving a no-op watcher or a misleading default.
"""
from __future__ import annotations

import os
import sys

from lingtai.kernel.refresh_watcher import RefreshWatcherPort


def select_refresh_watcher() -> RefreshWatcherPort:
    """Return the production refresh-watcher Port for this platform.

    This vertical slice ships production POSIX and Windows adapters. The
    selector is the capability-level registration point for either one and
    owns the fail-loud unsupported-platform behavior for anything else.
    """
    if sys.platform == "win32":
        from lingtai.adapters.windows.refresh_watcher import WindowsRefreshWatcherAdapter

        return WindowsRefreshWatcherAdapter()
    if os.name != "posix":
        raise NotImplementedError(
            f"No production refresh-watcher adapter for platform {sys.platform!r} "
            f"(os.name={os.name!r}). This vertical slice ships POSIX and Windows "
            "adapters; other non-POSIX platforms are out of scope."
        )
    from lingtai.adapters.posix.refresh_watcher import PosixRefreshWatcherAdapter

    return PosixRefreshWatcherAdapter()


__all__ = ["select_refresh_watcher"]

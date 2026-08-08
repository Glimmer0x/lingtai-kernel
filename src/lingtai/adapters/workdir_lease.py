"""Outer platform selector for the working-directory lease adapter.

This is composition-root wiring: it reads the running platform, selects the
concrete ``WorkdirLeasePort`` adapter, and constructs it. It is deliberately the
only place that branches on the operating system for leasing. Core never imports
this module — the composition roots (``lingtai.agent``, ``lingtai.cli``) call
``select_workdir_lease`` and inject the returned Port into ``BaseAgent`` and the
SQLite rebuild.

This slice ships production POSIX (``fcntl.flock``) and Windows (``msvcrt``
byte-range lock) adapters. On any other unsupported platform the selector
fails loudly rather than silently degrading.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from lingtai.kernel.workdir_lease import WorkdirLeasePort


def select_workdir_lease(working_dir: str | Path) -> WorkdirLeasePort:
    """Return the production working-directory lease for the current platform.

    Selects the native Windows (``msvcrt``) adapter on ``win32`` and the POSIX
    (``fcntl.flock``) adapter on every other ``os.name == "posix"`` platform.
    Raises ``NotImplementedError`` on every other platform without a production
    lease adapter. The rejection happens *before* the POSIX adapter (which
    imports ``fcntl`` at module top) is imported, so the unsupported-platform
    failure is this selector's explicit error rather than a bare ``fcntl``
    ``ModuleNotFoundError``. The failure is loud and explicit: there is no
    unlocked or no-op fallback.
    """
    if sys.platform == "win32":
        from lingtai.adapters.windows.workdir_lease import WindowsWorkdirLeaseAdapter

        return WindowsWorkdirLeaseAdapter(working_dir)
    if os.name != "posix":
        raise NotImplementedError(
            f"No production workdir-lease adapter for platform {sys.platform!r} "
            f"(os.name={os.name!r}). This vertical slice ships a POSIX flock "
            "adapter and a native Windows adapter; other non-POSIX platforms "
            "are out of scope."
        )
    from lingtai.adapters.posix.workdir_lease import PosixWorkdirLeaseAdapter

    return PosixWorkdirLeaseAdapter(working_dir)


__all__ = ["select_workdir_lease"]

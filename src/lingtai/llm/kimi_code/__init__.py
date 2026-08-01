"""Kimi Code provider — drive the local ``kimi`` CLI as a LingTai brain.

This is intentionally distinct from the generic HTTP ``kimi`` provider and
from the ``kimicode`` daemon backend.  The adapter owns canonical history and
requires the CLI to return LingTai JSON actions; its opaque resume identity is
used for provider cache affinity, and real cache-read usage is read from the
private session wire when Kimi persists it rather than fabricated.
"""

from __future__ import annotations

from .adapter import (
    KimiCodeAdapter,
    KimiCodeAuthError,
    KimiCodeChatSession,
    KimiCodeContextOverflow,
    KimiCodeError,
)

__all__ = [
    "KimiCodeAdapter",
    "KimiCodeChatSession",
    "KimiCodeError",
    "KimiCodeAuthError",
    "KimiCodeContextOverflow",
]

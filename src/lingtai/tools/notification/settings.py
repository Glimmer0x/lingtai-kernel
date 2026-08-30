"""Read-only discovery of Notification's two effective settings."""
from __future__ import annotations

from collections.abc import Callable

from lingtai.kernel.meta_block import NOTIFICATION_PERSISTENT_MAX_CHARS
from lingtai.kernel.notifications import DEFAULT_NOTIFICATION_DELAY_MAX_SECONDS
from lingtai.tools.tool_family import SettingRow

MAX_CHARS_KEY = "notification.max_chars"
DELAY_MAX_SECONDS_KEY = "notification.delay_max_seconds"

MAX_CHARS_COMMENT = (
    "notification-manual#block-size-cap-persistent-and-attention-lanes"
)
DELAY_MAX_SECONDS_COMMENT = (
    "notification-manual#consumer-delay-and-expiry-alarm"
)


def notification_settings(
    read_settings: Callable[[], tuple[int, int]],
) -> tuple[SettingRow, SettingRow]:
    """Return fresh effective values through the bound read-only callback."""
    max_chars, delay_max_seconds = read_settings()
    return (
        SettingRow(
            key=MAX_CHARS_KEY,
            current=max_chars,
            default=NOTIFICATION_PERSISTENT_MAX_CHARS,
            configurable=True,
            comment=MAX_CHARS_COMMENT,
        ),
        SettingRow(
            key=DELAY_MAX_SECONDS_KEY,
            current=delay_max_seconds,
            default=DEFAULT_NOTIFICATION_DELAY_MAX_SECONDS,
            configurable=True,
            comment=DELAY_MAX_SECONDS_COMMENT,
        ),
    )


__all__ = [
    "DELAY_MAX_SECONDS_COMMENT",
    "DELAY_MAX_SECONDS_KEY",
    "MAX_CHARS_COMMENT",
    "MAX_CHARS_KEY",
    "notification_settings",
]

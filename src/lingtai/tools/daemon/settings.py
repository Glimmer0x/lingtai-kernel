"""Read-only projection of the active Daemon owner's settings."""
from __future__ import annotations

from typing import Any

from ..tool_family import SettingRow
from .system_prompt import DAEMON_SYSTEM_PROMPT_BUDGET_CHARS

DEFAULT_DAEMON_MAX_TURNS = 5_000
DEFAULT_DAEMON_MANAGER_POOL_SIZE = 100
DEFAULT_DAEMON_TIMEOUT_SECONDS = 3_600.0

DAEMON_SETTING_KEYS = (
    "max_turns",
    "manager_pool_size",
    "system_prompt_budget_chars",
    "timeout",
)


def daemon_setting_rows(manager: Any) -> tuple[SettingRow, ...]:
    """Return fresh rows from the active manager's effective snapshot.

    Attribute access is intentionally strict: incomplete manager truth raises,
    allowing the generic settings action to fail the whole inventory instead
    of presenting partial or fabricated values.
    """
    return (
        SettingRow(
            "max_turns",
            manager._max_turns,
            DEFAULT_DAEMON_MAX_TURNS,
            True,
            "daemon-manual#max-turns",
        ),
        SettingRow(
            "manager_pool_size",
            manager._manager_pool_size,
            DEFAULT_DAEMON_MANAGER_POOL_SIZE,
            True,
            "daemon-manual#manager-pool-size",
        ),
        SettingRow(
            "system_prompt_budget_chars",
            manager._system_prompt_budget_chars,
            DAEMON_SYSTEM_PROMPT_BUDGET_CHARS,
            True,
            "daemon-manual#system-prompt-budget-chars",
        ),
        SettingRow(
            "timeout",
            manager._timeout,
            DEFAULT_DAEMON_TIMEOUT_SECONDS,
            True,
            "daemon-manual#timeout",
        ),
    )

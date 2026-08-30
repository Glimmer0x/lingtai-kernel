"""Cloud Mail's read-only, fully redacted settings provider."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from lingtai.tools.tool_family import SettingRow

CONFIG_ENV = "LINGTAI_CLOUD_MAIL_CONFIG"
CONFIG_PATH_COMMENT = "cloud-mail-mcp-manual#config-path"
ACCOUNTS_COMMENT = "cloud-mail-mcp-manual#accounts-document"


class _StartupSettingsSnapshot(Protocol):
    """The narrow applied snapshot exposed by a constructed manager."""

    @property
    def config_path(self) -> Path | None: ...


class CloudMailSettingsProvider:
    """Project startup truth without inspecting the account document."""

    def __init__(self, manager: _StartupSettingsSnapshot | None) -> None:
        self._manager = manager

    def __call__(self) -> tuple[SettingRow, SettingRow]:
        manager = self._manager
        config_path = None if manager is None else manager.config_path
        if config_path is None:
            raise RuntimeError("cloud_mail settings truth is unavailable")
        return (
            SettingRow(
                "config_path",
                str(config_path),
                None,
                True,
                CONFIG_PATH_COMMENT,
                _sensitive=True,
            ),
            SettingRow(
                "accounts",
                "configured",
                None,
                True,
                ACCOUNTS_COMMENT,
                _sensitive=True,
            ),
        )


__all__ = [
    "ACCOUNTS_COMMENT",
    "CONFIG_ENV",
    "CONFIG_PATH_COMMENT",
    "CloudMailSettingsProvider",
]

"""Read-only WeChat settings projected from the active manager snapshot."""
from __future__ import annotations

from typing import Any

from lingtai.tools.tool_family import SettingRow

from . import api

CONFIG_PATH_KEY = "config_path"
BASE_URL_KEY = "base_url"
POLL_INTERVAL_KEY = "poll_interval"
ALLOWED_USERS_KEY = "allowed_users"
BOT_TOKEN_KEY = "bot_token"
USER_ID_KEY = "user_id"

SETTING_KEYS = (
    CONFIG_PATH_KEY,
    BASE_URL_KEY,
    POLL_INTERVAL_KEY,
    ALLOWED_USERS_KEY,
    BOT_TOKEN_KEY,
    USER_ID_KEY,
)

_MANUAL = "wechat-mcp-manual"
COMMENT_BY_KEY = {
    CONFIG_PATH_KEY: f"{_MANUAL}#setting-config-path",
    BASE_URL_KEY: f"{_MANUAL}#setting-base-url",
    POLL_INTERVAL_KEY: f"{_MANUAL}#setting-poll-interval",
    ALLOWED_USERS_KEY: f"{_MANUAL}#setting-allowed-users",
    BOT_TOKEN_KEY: f"{_MANUAL}#setting-bot-token",
    USER_ID_KEY: f"{_MANUAL}#setting-user-id",
}


def wechat_settings(manager: Any | None) -> tuple[SettingRow, ...]:
    """Return the effective construction snapshot of one live manager."""
    if manager is None:
        raise RuntimeError("WeChat manager settings snapshot is unavailable")
    try:
        config_path = manager._settings_config_path
        base_url = manager._base_url
        poll_interval = manager._poll_interval
        allowed_users = manager._allowed_users
        bot_token = manager._token
        user_id = manager._user_id
    except AttributeError as exc:
        raise RuntimeError(
            "WeChat manager settings snapshot is unavailable"
        ) from exc
    if not config_path:
        raise RuntimeError("WeChat manager settings snapshot is unavailable")

    return (
        SettingRow(
            CONFIG_PATH_KEY,
            config_path,
            None,
            True,
            COMMENT_BY_KEY[CONFIG_PATH_KEY],
            _sensitive=True,
        ),
        SettingRow(
            BASE_URL_KEY,
            base_url,
            api.DEFAULT_BASE_URL,
            True,
            COMMENT_BY_KEY[BASE_URL_KEY],
            _sensitive=True,
        ),
        SettingRow(
            POLL_INTERVAL_KEY,
            poll_interval,
            1.0,
            True,
            COMMENT_BY_KEY[POLL_INTERVAL_KEY],
        ),
        SettingRow(
            ALLOWED_USERS_KEY,
            None if allowed_users is None else set(allowed_users),
            None,
            True,
            COMMENT_BY_KEY[ALLOWED_USERS_KEY],
            _sensitive=True,
        ),
        SettingRow(
            BOT_TOKEN_KEY,
            bot_token,
            None,
            True,
            COMMENT_BY_KEY[BOT_TOKEN_KEY],
            _sensitive=True,
        ),
        SettingRow(
            USER_ID_KEY,
            user_id,
            None,
            True,
            COMMENT_BY_KEY[USER_ID_KEY],
            _sensitive=True,
        ),
    )


__all__ = [
    "ALLOWED_USERS_KEY",
    "BASE_URL_KEY",
    "BOT_TOKEN_KEY",
    "COMMENT_BY_KEY",
    "CONFIG_PATH_KEY",
    "POLL_INTERVAL_KEY",
    "SETTING_KEYS",
    "USER_ID_KEY",
    "wechat_settings",
]

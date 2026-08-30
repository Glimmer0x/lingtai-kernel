"""Read-only Feishu settings projected from the bound live service."""
from __future__ import annotations

from typing import Any

from lingtai.mcp_servers.task_card import TaskCardEventProjection
from lingtai.tools.tool_family import SettingRow

CONFIG_PATH = "config.path"
ACCOUNT_ALIASES = "accounts.aliases"
ACCOUNT_APP_IDS = "accounts.app_ids"
ACCOUNT_APP_SECRETS = "accounts.app_secrets"
ACCOUNT_ALLOWED_USERS = "accounts.allowed_users"
TASKCARD_ENABLED = "taskcard.enabled"
TASKCARD_NORMAL_ROWS = "taskcard.normal_rows"

CONFIG_PATH_COMMENT = "feishu-mcp-manual#setting-config-path"
ACCOUNT_ALIASES_COMMENT = "feishu-mcp-manual#setting-account-aliases"
ACCOUNT_APP_IDS_COMMENT = "feishu-mcp-manual#setting-account-app-ids"
ACCOUNT_APP_SECRETS_COMMENT = "feishu-mcp-manual#setting-account-app-secrets"
ACCOUNT_ALLOWED_USERS_COMMENT = "feishu-mcp-manual#setting-account-allowed-users"
TASKCARD_ENABLED_COMMENT = "feishu-mcp-manual#setting-task-card-enabled"
TASKCARD_NORMAL_ROWS_COMMENT = "feishu-mcp-manual#setting-task-card-normal-rows"


def build_feishu_settings(manager: Any | None) -> tuple[SettingRow, ...]:
    """Return fresh Feishu-owned display facts or fail the whole inventory."""
    service = getattr(manager, "_service", None)
    if service is None:
        raise RuntimeError("Feishu settings require a live service")

    config_source = getattr(service, "_config_source", None)
    if not isinstance(config_source, str) or not config_source:
        raise RuntimeError("Feishu configuration source is unavailable")

    aliases = service.list_accounts()
    accounts = [service.get_account(alias) for alias in aliases]
    app_ids = [account._app_id for account in accounts]
    app_secrets = [account._app_secret for account in accounts]
    allowed_users = [
        None
        if account._allowed_users is None
        else tuple(account._allowed_users)
        for account in accounts
    ]

    return (
        SettingRow(
            CONFIG_PATH,
            config_source,
            None,
            True,
            CONFIG_PATH_COMMENT,
            _sensitive=True,
        ),
        SettingRow(
            ACCOUNT_ALIASES,
            aliases,
            None,
            True,
            ACCOUNT_ALIASES_COMMENT,
        ),
        SettingRow(
            ACCOUNT_APP_IDS,
            app_ids,
            None,
            True,
            ACCOUNT_APP_IDS_COMMENT,
        ),
        SettingRow(
            ACCOUNT_APP_SECRETS,
            app_secrets,
            None,
            True,
            ACCOUNT_APP_SECRETS_COMMENT,
            _sensitive=True,
        ),
        SettingRow(
            ACCOUNT_ALLOWED_USERS,
            allowed_users,
            None,
            True,
            ACCOUNT_ALLOWED_USERS_COMMENT,
            _sensitive=True,
        ),
        SettingRow(
            TASKCARD_ENABLED,
            service.taskcard_enabled(),
            True,
            True,
            TASKCARD_ENABLED_COMMENT,
        ),
        SettingRow(
            TASKCARD_NORMAL_ROWS,
            service.taskcard_normal_rows(),
            TaskCardEventProjection.DEFAULT_NORMAL_ROWS,
            True,
            TASKCARD_NORMAL_ROWS_COMMENT,
        ),
    )

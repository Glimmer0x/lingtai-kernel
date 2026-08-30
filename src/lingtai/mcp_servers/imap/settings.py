"""Read-only IMAP settings projection over the running manager snapshot."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from lingtai.tools.tool_family import SettingRow

IMAP_CONFIG_ENV = "LINGTAI_IMAP_CONFIG"
_MANUAL = "imap-mcp-manual"


def imap_setting_rows(manager: Any | None) -> tuple[SettingRow, ...]:
    """Return one coherent applied snapshot or raise when truth is unavailable."""
    if manager is None:
        raise RuntimeError("IMAP manager is unavailable")

    config_path = manager._config_path
    accounts = manager._service.accounts
    if config_path is None or not accounts:
        raise RuntimeError("IMAP startup settings are unavailable")

    addresses: list[str] = []
    credentials: list[str] = []
    imap_endpoints: list[str] = []
    smtp_endpoints: list[str] = []
    oauth_configuration: list[str] = []

    for account in accounts:
        auth = account._auth
        if auth and not isinstance(auth, Mapping):
            raise RuntimeError("IMAP OAuth configuration is unavailable")

        addresses.append(str(account.address))
        credentials.append(
            "oauth-configured"
            if auth
            else (
                "password-configured"
                if account._email_password
                else "unconfigured"
            )
        )
        imap_endpoints.append(f"{account._imap_host}:{account._imap_port}")
        smtp_endpoints.append(f"{account._smtp_host}:{account._smtp_port}")
        oauth_configuration.append(
            "not-configured"
            if not auth
            else (
                f"type={auth.get('type', 'missing')};"
                f"client_id={'configured' if auth.get('client_id') else 'missing'};"
                f"token_cache={'configured' if auth.get('token_cache') else 'missing'}"
            )
        )

    private = {"configurable": True, "_sensitive": True}
    return (
        SettingRow(
            "config_reference",
            str(config_path),
            None,
            comment=f"{_MANUAL}#config-reference",
            **private,
        ),
        SettingRow(
            "account_addresses",
            addresses,
            None,
            comment=f"{_MANUAL}#account-addresses",
            **private,
        ),
        SettingRow(
            "credentials",
            credentials,
            None,
            comment=f"{_MANUAL}#credentials",
            **private,
        ),
        SettingRow(
            "imap_endpoints",
            imap_endpoints,
            ["imap.gmail.com:993"],
            comment=f"{_MANUAL}#imap-endpoints",
            **private,
        ),
        SettingRow(
            "smtp_endpoints",
            smtp_endpoints,
            ["smtp.gmail.com:587"],
            comment=f"{_MANUAL}#smtp-endpoints",
            **private,
        ),
        SettingRow(
            "oauth_configuration",
            oauth_configuration,
            [],
            comment=f"{_MANUAL}#oauth-configuration",
            **private,
        ),
    )

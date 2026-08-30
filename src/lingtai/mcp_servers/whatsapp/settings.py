"""Read-only WhatsApp settings projected through the generic five-field seam."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lingtai.tools.tool_family import SettingRow, SettingsProvider

from . import client as bridge_client


def _rows(manager: Any) -> tuple[SettingRow, ...]:
    """Return one complete inventory from the manager's startup snapshot."""
    working_dir = manager.working_dir
    allowed_wa_ids = manager.allowed_wa_ids
    return (
        SettingRow(
            "config_reference",
            str(manager.config_path) if manager.config_path is not None else None,
            None,
            True,
            "whatsapp-mcp-manual#config-reference",
            _sensitive=True,
        ),
        SettingRow(
            "node_path",
            str(manager.bridge.node_path),
            bridge_client._default_node(),
            True,
            "whatsapp-mcp-manual#node-path",
            _sensitive=True,
        ),
        SettingRow(
            "bridge_dir",
            str(manager.bridge.bridge_dir),
            str(bridge_client._bridge_dir()),
            True,
            "whatsapp-mcp-manual#bridge-directory",
            _sensitive=True,
        ),
        SettingRow(
            "session_dir",
            str(manager.session_dir),
            str(working_dir / ".wwebjs_auth"),
            True,
            "whatsapp-mcp-manual#session-directory",
            _sensitive=True,
        ),
        SettingRow(
            "store_dir",
            str(manager.store_dir),
            str(working_dir / "whatsapp"),
            True,
            "whatsapp-mcp-manual#message-store-directory",
            _sensitive=True,
        ),
        SettingRow(
            "allowed_wa_ids",
            None if allowed_wa_ids is None else sorted(allowed_wa_ids),
            None,
            True,
            "whatsapp-mcp-manual#allowed-whatsapp-ids",
            _sensitive=True,
        ),
        SettingRow(
            "autostart",
            manager.autostart,
            True,
            True,
            "whatsapp-mcp-manual#autostart",
        ),
    )


def settings_provider(manager: Any | None) -> SettingsProvider:
    """Bind SHOW to a manager; an absent manager fails as one inventory."""
    if manager is None:
        def unavailable() -> Iterable[SettingRow]:
            raise RuntimeError("WhatsApp manager startup facts are unavailable")

        return unavailable
    return lambda: _rows(manager)

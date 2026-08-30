"""Read-only SHOW projection of MCP-owned top-level init settings."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..tool_family import SettingRow

_MANUAL_ANCHOR = "mcp-manual#configuration-settings"


class MCPSettingsProvider:
    """Read the canonical effective init document afresh for each SHOW."""

    def __init__(self, working_dir: Path | None) -> None:
        self._working_dir = working_dir

    def __call__(self) -> list[SettingRow]:
        if self._working_dir is None:
            raise RuntimeError("MCP settings require a bound working directory")

        # Keep the tools -> lingtai back-edge lazy and reuse the same reader as
        # boot/refresh.  A failed canonical read makes the whole inventory
        # unavailable; no raw-file fallback or partial rows are projected.
        from lingtai.agent import load_preset
        from lingtai.init_reader import read_init, reader_callbacks

        materialize, prepare = reader_callbacks(
            self._working_dir,
            load_preset=load_preset,
        )
        outcome = read_init(
            self._working_dir,
            materialize=materialize,
            prepare=prepare,
        )
        data = outcome.data
        if not outcome.ok or not isinstance(data, dict):
            raise RuntimeError(
                f"effective init configuration is unavailable at {outcome.stage or 'UNKNOWN'}"
            )

        addons: Any = data.get("addons", [])
        mcp: Any = data.get("mcp", {})
        if not isinstance(addons, list) or any(
            not isinstance(addon, str) for addon in addons
        ):
            raise RuntimeError("effective init.addons is unavailable")
        if not isinstance(mcp, dict):
            raise RuntimeError("effective init.mcp is unavailable")

        return [
            SettingRow(
                key="init.addons",
                current=list(addons),
                default=[],
                configurable=True,
                comment=_MANUAL_ANCHOR,
            ),
            SettingRow(
                key="init.mcp",
                current=mcp,
                default={},
                configurable=True,
                comment=_MANUAL_ANCHOR,
                _sensitive=True,
            ),
        ]

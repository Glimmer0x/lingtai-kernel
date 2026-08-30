"""Plugin-owned settings inventory over the detached registration snapshot."""
from __future__ import annotations

from lingtai.kernel.tool_plugin import PluginCatalogPort

from ..tool_family import SettingRow


def plugin_setting_rows(catalog: PluginCatalogPort | None) -> tuple[SettingRow, ...]:
    """Return the folded configured roots without scanning or mutation."""
    if catalog is None:
        raise RuntimeError("Plugin catalog is unavailable")

    configured = catalog.read_state().registration.get("configured_declared")
    if not isinstance(configured, (list, tuple)) or any(
        not isinstance(path, str) for path in configured
    ):
        raise RuntimeError("Plugin registration snapshot is unavailable")

    return (
        SettingRow(
            key="manifest.plugins",
            current=list(configured),
            default=[],
            configurable=True,
            comment="plugin-manual#plugin-registration-roots",
            _sensitive=True,
        ),
    )


__all__ = ["plugin_setting_rows"]

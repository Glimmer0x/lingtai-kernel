"""Read-only projection of Soul's live settings."""
from __future__ import annotations

import math
from typing import TYPE_CHECKING

from lingtai.kernel.config import DEFAULT_SOUL_DELAY_SECONDS

from ..tool_family import SettingRow, SettingsProvider
from .flow import _soul_flow_enabled

if TYPE_CHECKING:
    from lingtai.kernel.tool_plugin import SoulRuntimePort


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RuntimeError(f"Soul {name} is unavailable")
    current = float(value)
    if not math.isfinite(current):
        raise RuntimeError(f"Soul {name} is unavailable")
    return current


def _integer(value: object, name: str) -> int:
    if type(value) is not int:
        raise RuntimeError(f"Soul {name} is unavailable")
    return value


def _text(value: object, name: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise RuntimeError(f"Soul {name} is unavailable")
    value.encode("utf-8")
    return value


def soul_settings_provider(runtime: "SoulRuntimePort") -> SettingsProvider:
    """Bind a fresh five-row SHOW provider to one live Soul runtime."""

    def provide() -> tuple[SettingRow, ...]:
        config = runtime.config
        return (
            SettingRow(
                "flow_enabled",
                _soul_flow_enabled(),
                False,
                True,
                "soul-manual#flow-enabled",
            ),
            SettingRow(
                "delay_seconds",
                _finite_number(runtime.soul_delay, "delay_seconds"),
                DEFAULT_SOUL_DELAY_SECONDS,
                True,
                "soul-manual#delay-seconds",
            ),
            SettingRow(
                "consultation_past_count",
                _integer(
                    config.consultation_past_count,
                    "consultation_past_count",
                ),
                0,
                True,
                "soul-manual#consultation-past-count",
            ),
            SettingRow(
                "voice",
                _text(config.soul_voice, "voice"),
                "inner",
                True,
                "soul-manual#voice",
            ),
            SettingRow(
                "voice_prompt",
                _text(config.soul_voice_prompt, "voice_prompt", allow_empty=True),
                None,
                True,
                "soul-manual#voice-prompt",
                _sensitive=True,
            ),
        )

    return provide

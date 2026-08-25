"""Small, read-only settings owner for the System tool family."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CACHE_MISS_BUDGET_ENV = "LINGTAI_CACHE_MISS_BUDGET"
DEFAULT_CACHE_MISS_BUDGET = 2_000_000
SYSTEM_SETTINGS_RELATIVE_PATH = Path("settings") / "system.json"
_SYSTEM_SETTINGS_SCHEMA_VERSION = 1


def _positive_int(value: Any) -> int | None:
    if type(value) is int and value > 0:
        return value
    if isinstance(value, str):
        try:
            parsed = int(value.strip())
        except (TypeError, ValueError):
            return None
        if parsed > 0:
            return parsed
    return None


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _parse_settings(text: str) -> int | None:
    try:
        data = json.loads(text, object_pairs_hook=_closed_object)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or set(data) != {
        "schema_version",
        "cache_miss_budget",
    }:
        return None
    if (
        type(data["schema_version"]) is not int
        or data["schema_version"] != _SYSTEM_SETTINGS_SCHEMA_VERSION
    ):
        return None
    budget = data["cache_miss_budget"]
    return budget if type(budget) is int and budget > 0 else None


def resolve_cache_miss_budget(agent: Any) -> int:
    """Resolve live env, then System JSON, then the fixed positive default."""
    env_budget = _positive_int(os.environ.get(CACHE_MISS_BUDGET_ENV))
    if env_budget is not None:
        return env_budget

    path = Path(agent._working_dir) / SYSTEM_SETTINGS_RELATIVE_PATH
    try:
        budget = _parse_settings(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        budget = None
    return budget if budget is not None else DEFAULT_CACHE_MISS_BUDGET

"""Low-frequency, advisory-only direct count of the active event journal.

The expensive observation is deliberately bounded to once per UTC day for an
unchanged file. It counts physical newline-delimited records directly from the
active root JSONL file and never parses, rebuilds, checkpoints, or otherwise
changes journal data.
"""
from __future__ import annotations

import json
import os
import stat as stat_module
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_KIND = "event_journal_line_count"
_THRESHOLD_RECORDS = 1_000_000
_STATE_FILE = Path(".notification") / ".nudge_state.json"
_CHUNK_BYTES = 1024 * 1024


def observation_due(agent) -> bool:
    """Return whether an inexpensive metadata check found a fresh count due."""
    events_path = Path(agent._working_dir) / "logs" / "events.jsonl"
    opened = _open_regular_event_file(events_path)
    state_root = _load_persistent_state(agent)
    state = state_root.get(_KIND)
    if not isinstance(state, dict):
        state = {}
    if opened is None:
        return state.get("available") is not False
    fd, source_stat = opened
    try:
        identity = [source_stat.st_dev, source_stat.st_ino]
        previous_size = state.get("size_bytes")
        return (
            state.get("available") is not True
            or state.get("last_check_date") != _today_utc()
            or state.get("file_identity") != identity
            or not isinstance(previous_size, int)
            or source_stat.st_size < previous_size
        )
    finally:
        os.close(fd)


def observe(agent) -> bool:
    """Read/counter the event journal when due, outside the heartbeat thread."""
    events_path = Path(agent._working_dir) / "logs" / "events.jsonl"
    opened = _open_regular_event_file(events_path)
    state_root = _load_persistent_state(agent)
    state = state_root.setdefault(_KIND, {})
    if opened is None:
        if state.get("available") is not False:
            state.clear()
            state["available"] = False
            _save_persistent_state(agent, state_root)
        return False

    fd, source_stat = opened
    try:
        identity = [source_stat.st_dev, source_stat.st_ino]
        today = _today_utc()
        previous_size = state.get("size_bytes")
        needs_count = (
            state.get("available") is not True
            or state.get("last_check_date") != today
            or state.get("file_identity") != identity
            or not isinstance(previous_size, int)
            or source_stat.st_size < previous_size
        )
        if not needs_count:
            return False
        try:
            record_count = _count_newline_records(fd)
        except OSError:
            record_count = None
        state.update(
            {
                "available": True,
                "last_check_date": today,
                "file_identity": identity,
                "size_bytes": source_stat.st_size,
                "record_count": record_count,
            }
        )
        _save_persistent_state(agent, state_root)
        return record_count is not None
    finally:
        os.close(fd)


def evaluate(agent) -> None:
    """Render the last persisted observation without opening or reading history."""
    from . import remove, upsert

    state_root = _load_persistent_state(agent)
    state = state_root.get(_KIND)
    if not isinstance(state, dict) or state.get("available") is not True:
        remove(agent, _KIND)
        return
    record_count = state.get("record_count")
    if not isinstance(record_count, int) or record_count < _THRESHOLD_RECORDS:
        remove(agent, _KIND)
        return

    events_path = Path(agent._working_dir) / "logs" / "events.jsonl"
    upsert(
        agent,
        _KIND,
        {
            "title": "Active event journal reached 1,000,000 records",
            "detail": (
                "A low-frequency agent-folder organization check directly counted "
                "at least 1,000,000 newline-delimited records in the active root "
                "events.jsonl. Discuss handling with your human before taking any "
                "action. This advisory does not automatically rename, create a new "
                "file, archive, delete, compress, parse, rebuild, or otherwise "
                "change journal data."
            ),
            "source": "direct-event-journal-count",
            "active_events_path": str(events_path),
            "threshold_records": _THRESHOLD_RECORDS,
            "cadence": "once per UTC day for an unchanged file; immediate re-count after identity change or shrink",
        },
    )


def check(agent) -> None:
    """Synchronously observe then evaluate for explicit/manual callers."""
    observe(agent)
    evaluate(agent)

def _open_regular_event_file(path: Path) -> tuple[int, os.stat_result] | None:
    """Open exactly ``path`` without link-following, or return quiet unknown."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        return None
    flags = os.O_RDONLY | nofollow | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        source_stat = os.fstat(fd)
        if not stat_module.S_ISREG(source_stat.st_mode):
            os.close(fd)
            return None
        return fd, source_stat
    except OSError:
        os.close(fd)
        return None


def _count_newline_records(fd: int) -> int:
    """Count physical newline records without retaining or interpreting content."""
    count = 0
    while chunk := os.read(fd, _CHUNK_BYTES):
        count += chunk.count(b"\n")
    return count


def _today_utc() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _persistent_path(agent) -> Path:
    return Path(agent._working_dir) / _STATE_FILE


def _load_persistent_state(agent) -> dict[str, Any]:
    path = _persistent_path(agent)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_persistent_state(agent, state: dict[str, Any]) -> None:
    path = _persistent_path(agent)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


__all__ = ["check", "evaluate", "observation_due", "observe"]

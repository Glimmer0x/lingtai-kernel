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


def check(agent) -> None:
    """Evaluate a direct count at most once per UTC day for an unchanged file.

    Every heartbeat opens the exact active path with a non-following,
    non-blocking descriptor and only fstats it. A whole-file read is due on a
    new UTC date, a file identity change, or a shrink. Missing, linked,
    non-regular, or unreadable paths are quiet no-findings.
    """
    from . import remove, upsert

    events_path = Path(agent._working_dir) / "logs" / "events.jsonl"
    opened = _open_regular_event_file(events_path)
    if opened is None:
        remove(agent, _KIND)
        return

    fd, source_stat = opened
    try:
        state_root = _load_persistent_state(agent)
        state = state_root.setdefault(_KIND, {})
        identity = [source_stat.st_dev, source_stat.st_ino]
        today = _today_utc()
        previous_size = state.get("size_bytes")
        needs_count = (
            state.get("last_check_date") != today
            or state.get("file_identity") != identity
            or not isinstance(previous_size, int)
            or source_stat.st_size < previous_size
        )

        if needs_count:
            try:
                record_count = _count_newline_records(fd)
            except OSError:
                state.update(
                    {
                        "last_check_date": today,
                        "file_identity": identity,
                        "size_bytes": source_stat.st_size,
                        "record_count": None,
                    }
                )
                _save_persistent_state(agent, state_root)
                remove(agent, _KIND)
                return
            state.update(
                {
                    "last_check_date": today,
                    "file_identity": identity,
                    "size_bytes": source_stat.st_size,
                    "record_count": record_count,
                }
            )
            _save_persistent_state(agent, state_root)

        record_count = state.get("record_count")
    finally:
        os.close(fd)

    if not isinstance(record_count, int) or record_count < _THRESHOLD_RECORDS:
        remove(agent, _KIND)
        return

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


__all__ = ["check"]

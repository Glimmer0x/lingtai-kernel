from __future__ import annotations

import os
from pathlib import Path

import pytest

from lingtai.kernel import nudge as nudge_mod
from lingtai.kernel.nudge import ENTRY_CHANNEL_STORAGE_SIZE
from lingtai.kernel.nudge import event_journal_count
from tests._notification_store_helpers import notification_store_for, snapshot_notifications


class _Agent:
    def __init__(self, workdir: Path) -> None:
        self._working_dir = workdir
        self._notification_store = notification_store_for(workdir)
        self._notification_fp = ()
        self.logs: list[tuple[str, dict]] = []

    def _log(self, event: str, **fields) -> None:
        self.logs.append((event, fields))


def _entries(workdir: Path) -> list[dict]:
    return snapshot_notifications(workdir).get("nudge", {}).get("data", {}).get("nudges", [])


def _events_path(workdir: Path, data: bytes = b"seed\n") -> Path:
    path = workdir / "logs" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture(autouse=True)
def _fixed_day(monkeypatch) -> None:
    monkeypatch.setattr(event_journal_count, "_today_utc", lambda: "2026-08-16")


def test_exact_threshold_emits_human_discussion_advisory(monkeypatch, tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    path = _events_path(tmp_path)
    monkeypatch.setattr(
        event_journal_count,
        "_count_newline_records",
        lambda _: event_journal_count._THRESHOLD_RECORDS,
    )

    event_journal_count.check(agent)

    entry = _entries(tmp_path)[0]
    assert entry["kind"] == "event_journal_line_count"
    assert entry["nudge_channel"] == ENTRY_CHANNEL_STORAGE_SIZE
    assert entry["active_events_path"] == str(path)
    assert entry["threshold_records"] == event_journal_count._THRESHOLD_RECORDS
    assert entry["cadence"] == "once per UTC day for an unchanged file; immediate re-count after identity change or shrink"
    assert "Discuss handling with your human" in entry["detail"]
    for boundary in ("rename", "create a new file", "archive", "delete", "compress"):
        assert boundary in entry["detail"]


def test_under_threshold_clears_stale_finding(monkeypatch, tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    _events_path(tmp_path)
    nudge_mod.upsert(agent, "event_journal_line_count", {"title": "stale", "detail": "old"})
    monkeypatch.setattr(event_journal_count, "_count_newline_records", lambda _: 999_999)

    event_journal_count.check(agent)

    assert _entries(tmp_path) == []


def test_missing_file_is_quiet_no_finding(tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    nudge_mod.upsert(agent, "event_journal_line_count", {"title": "stale", "detail": "old"})

    event_journal_count.check(agent)

    assert _entries(tmp_path) == []


def test_unchanged_file_does_not_repeat_direct_count(monkeypatch, tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    path = _events_path(tmp_path)
    calls: list[int] = []

    def count(fd: int) -> int:
        calls.append(fd)
        return 0

    monkeypatch.setattr(event_journal_count, "_count_newline_records", count)
    event_journal_count.check(agent)
    event_journal_count.check(agent)

    assert len(calls) == 1
    assert path.exists()


def test_utc_date_rollover_recounts_unchanged_file(monkeypatch, tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    _events_path(tmp_path)
    day = ["2026-08-16"]
    calls: list[int] = []
    monkeypatch.setattr(event_journal_count, "_today_utc", lambda: day[0])
    monkeypatch.setattr(event_journal_count, "_count_newline_records", lambda fd: calls.append(fd) or 0)

    event_journal_count.check(agent)
    day[0] = "2026-08-17"
    event_journal_count.check(agent)

    assert len(calls) == 2


def test_same_size_replacement_recounts_immediately(monkeypatch, tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    path = _events_path(tmp_path, b"first\n")
    counts = iter([event_journal_count._THRESHOLD_RECORDS, 0])
    monkeypatch.setattr(event_journal_count, "_count_newline_records", lambda _: next(counts))

    event_journal_count.check(agent)
    assert len(_entries(tmp_path)) == 1
    replacement = path.with_name("replacement.jsonl")
    replacement.write_bytes(b"other\n")
    replacement.replace(path)
    event_journal_count.check(agent)

    assert _entries(tmp_path) == []


def test_shrink_recounts_same_day_and_clears_stale_observation(monkeypatch, tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    path = _events_path(tmp_path, b"a\n" * 20)
    counts = iter([event_journal_count._THRESHOLD_RECORDS, 0])
    monkeypatch.setattr(event_journal_count, "_count_newline_records", lambda _: next(counts))

    event_journal_count.check(agent)
    assert len(_entries(tmp_path)) == 1
    path.write_bytes(b"small\n")
    event_journal_count.check(agent)

    assert _entries(tmp_path) == []


def test_symlink_is_quiet_and_never_counts(monkeypatch, tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    path = _events_path(tmp_path)
    target = tmp_path / "outside.jsonl"
    target.write_bytes(b"outside\n")
    path.unlink()
    path.symlink_to(target)
    monkeypatch.setattr(event_journal_count, "_count_newline_records", lambda _: pytest.fail("must not count a link"))

    event_journal_count.check(agent)

    assert _entries(tmp_path) == []


def test_fifo_is_quiet_and_never_blocks_or_counts(monkeypatch, tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    path = _events_path(tmp_path)
    path.unlink()
    os.mkfifo(path)
    monkeypatch.setattr(event_journal_count, "_count_newline_records", lambda _: pytest.fail("must not count a FIFO"))

    event_journal_count.check(agent)

    assert _entries(tmp_path) == []


def test_unavailable_open_is_quiet_no_finding(monkeypatch, tmp_path: Path) -> None:
    agent = _Agent(tmp_path)
    _events_path(tmp_path)
    nudge_mod.upsert(agent, "event_journal_line_count", {"title": "stale", "detail": "old"})
    monkeypatch.setattr(event_journal_count, "_open_regular_event_file", lambda _: None)

    event_journal_count.check(agent)

    assert _entries(tmp_path) == []


def test_counter_uses_physical_newlines_without_json_interpretation(tmp_path: Path) -> None:
    path = _events_path(tmp_path, b"not-json\n{also-not-json}\nunterminated")
    opened = event_journal_count._open_regular_event_file(path)
    assert opened is not None
    fd, _ = opened
    try:
        assert event_journal_count._count_newline_records(fd) == 2
    finally:
        os.close(fd)

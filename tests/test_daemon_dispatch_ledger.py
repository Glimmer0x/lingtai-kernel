"""Focused invariants for append-only daemon dispatch membership."""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from lingtai.kernel import daemon_dispatch


def _append_from_process(args: tuple[str, int]) -> int:
    working_dir, index = args
    return daemon_dispatch.append_dispatch(
        working_dir,
        run_id=f"em-{index}",
        created_at="2026-08-24T00:00:00Z",
    ).sequence


def test_append_starts_at_one_and_cross_process_appends_are_continuous(tmp_path: Path) -> None:
    with ProcessPoolExecutor(max_workers=8) as pool:
        sequences = list(pool.map(_append_from_process, [(str(tmp_path), index) for index in range(40)]))

    assert sorted(sequences) == list(range(1, 41))
    read = daemon_dispatch.read_dispatches(tmp_path, full_history=True)
    assert [record.sequence for record in read.records] == list(range(1, 41))
    assert len({record.run_id for record in read.records}) == 40


def test_malformed_tail_fails_loud_without_repair_or_append(tmp_path: Path) -> None:
    path = daemon_dispatch.ledger_path(tmp_path)
    path.parent.mkdir(parents=True)
    original = b'{"schema":"lingtai.daemon_dispatch/v1","sequence":1}\nnot-json'
    path.write_bytes(original)

    with pytest.raises(daemon_dispatch.DispatchLedgerError, match="tail"):
        daemon_dispatch.append_dispatch(
            tmp_path,
            run_id="em-new",
            created_at="2026-08-24T00:00:00Z",
        )

    assert path.read_bytes() == original


def test_default_tail_is_bounded_in_append_order(tmp_path: Path) -> None:
    for index in range(1005):
        daemon_dispatch.append_dispatch(
            tmp_path,
            run_id=f"em-{index}",
            created_at="2026-08-24T00:00:00Z",
        )

    read = daemon_dispatch.read_dispatches(tmp_path)
    assert len(read.records) == 1000
    assert read.checked == {
        "source": "tail",
        "requested_limit": 1000,
        "records_read": 1000,
        "sequence_from": 6,
        "sequence_to": 1005,
    }
    assert read.records[0].run_id == "em-5"
    assert read.records[-1].run_id == "em-1004"


def test_checked_range_warnings_are_advisory_and_bounded(tmp_path: Path) -> None:
    path = daemon_dispatch.ledger_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text(
        "\n".join(
            [
                '{"schema":"lingtai.daemon_dispatch/v1","sequence":1,"run_id":"em-one","created_at":"a"}',
                'not-json',
                '{"schema":"lingtai.daemon_dispatch/v1","sequence":3,"run_id":"em-one","created_at":"a"}',
            ]
        ) + "\n",
        encoding="utf-8",
    )

    read, rows, warnings = daemon_dispatch.read_recent_daemon_states(tmp_path)
    assert rows == []
    codes = [warning["code"] for warning in warnings]
    assert codes == [
        "dispatch_ledger_invalid_record",
        "dispatch_ledger_sequence_non_monotonic",
        "dispatch_ledger_duplicate_run_id",
        "dispatch_ledger_daemon_state_unreadable",
    ]
    for warning in warnings:
        assert warning["checked"]["source"] == "tail"
        assert warning["manual"] == daemon_dispatch.MANUAL_PATH


def test_recovery_markers_only_return_current_unresolved_work(tmp_path: Path) -> None:
    daemon_dispatch.mark_running(tmp_path, "em-running", sequence=7)
    daemon_dispatch.mark_pending_terminal_notification(tmp_path, "em-pending", sequence=8)
    assert {(kind, run_id) for kind, run_id, _ in daemon_dispatch.recovery_markers(tmp_path)} == {
        ("running", "em-running"),
        ("pending-terminal", "em-pending"),
    }
    daemon_dispatch.clear_marker(tmp_path, "running", "em-running")
    assert {(kind, run_id) for kind, run_id, _ in daemon_dispatch.recovery_markers(tmp_path)} == {
        ("pending-terminal", "em-pending"),
    }

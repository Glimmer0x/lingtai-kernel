"""Append-only dispatch ledger and bounded recovery markers for daemon runs.

The ledger deliberately records acceptance order only.  ``daemon.json`` remains
status truth; this module neither changes it nor attempts to heal malformed
history.  The small marker directory contains only unresolved running and
terminal-notification work, so normal construction never needs to enumerate
lifetime run directories.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from lingtai.kernel._fsutil import atomic_write_json


LEDGER_SCHEMA = "lingtai.daemon_dispatch/v1"
LEDGER_FILENAME = ".dispatch-ledger.jsonl"
RECOVERY_DIRNAME = ".dispatch-recovery"
MANUAL_PATH = "src/lingtai/tools/daemon/manual/reference/dispatch-ledger/SKILL.md"
_DEFAULT_TAIL = 1000
_MAX_WARNING_EXAMPLES = 3


class DispatchLedgerError(RuntimeError):
    """A durable acceptance record cannot be safely appended."""


@dataclass(frozen=True)
class DispatchRecord:
    schema: str
    sequence: int
    run_id: str
    created_at: str

    def wire(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "sequence": self.sequence,
            "run_id": self.run_id,
            "created_at": self.created_at,
        }


@dataclass(frozen=True)
class LedgerRead:
    records: tuple[DispatchRecord, ...]
    warnings: tuple[dict[str, Any], ...]
    checked: dict[str, Any]


def daemons_dir(working_dir: Path | str) -> Path:
    return Path(working_dir) / "daemons"


def ledger_path(working_dir: Path | str) -> Path:
    return daemons_dir(working_dir) / LEDGER_FILENAME


def recovery_dir(working_dir: Path | str) -> Path:
    return daemons_dir(working_dir) / RECOVERY_DIRNAME


def _marker_path(working_dir: Path | str, kind: str, run_id: str) -> Path:
    return recovery_dir(working_dir) / f"{kind}-{run_id}.json"


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    """Serialize agent-scoped allocation on POSIX and native Windows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        import msvcrt

        with open(path, "a+b") as handle:
            handle.seek(0)
            if path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            while True:
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.01)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    with open(path, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _last_line(path: Path) -> bytes | None:
    """Return the final physical record without scanning prior history."""
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return None
    if size == 0:
        return None
    with path.open("rb") as handle:
        position = size
        chunks: list[bytes] = []
        while position:
            step = min(position, 8192)
            position -= step
            handle.seek(position)
            chunk = handle.read(step)
            chunks.append(chunk)
            joined = b"".join(reversed(chunks))
            # Preserve a partial final line: it is malformed and must block
            # future append rather than being silently skipped.
            if b"\n" in joined:
                return joined.rsplit(b"\n", 1)[-1] or joined.rstrip(b"\n").rsplit(b"\n", 1)[-1]
        return b"".join(reversed(chunks))


def _parse_record(raw: bytes | str) -> DispatchRecord:
    try:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        payload = json.loads(text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DispatchLedgerError("dispatch ledger tail is not valid JSON; refuse to append") from exc
    if not isinstance(payload, dict):
        raise DispatchLedgerError("dispatch ledger tail is not an object; refuse to append")
    schema = payload.get("schema")
    sequence = payload.get("sequence")
    run_id = payload.get("run_id")
    created_at = payload.get("created_at")
    if (
        schema != LEDGER_SCHEMA
        or isinstance(sequence, bool)
        or not isinstance(sequence, int)
        or sequence < 1
        or not isinstance(run_id, str)
        or not run_id
        or not isinstance(created_at, str)
        or not created_at
    ):
        raise DispatchLedgerError("dispatch ledger tail has an invalid schema; refuse to append")
    return DispatchRecord(schema=schema, sequence=sequence, run_id=run_id, created_at=created_at)


def append_dispatch(working_dir: Path | str, *, run_id: str, created_at: str) -> DispatchRecord:
    """Durably append one accepted run after initial ``daemon.json`` exists.

    The caller launches nothing until this returns.  Only the final record is
    consulted to allocate ``sequence + 1``; malformed tails fail loud and are
    never repaired, reordered, or truncated.
    """
    if not isinstance(run_id, str) or not run_id:
        raise DispatchLedgerError("dispatch ledger requires a non-empty run_id")
    if not isinstance(created_at, str) or not created_at:
        raise DispatchLedgerError("dispatch ledger requires a non-empty created_at")
    path = ledger_path(working_dir)
    lock = path.with_name(".dispatch-ledger.lock")
    with _ledger_lock(lock):
        tail = _last_line(path)
        sequence = 1 if tail is None else _parse_record(tail).sequence + 1
        record = DispatchRecord(LEDGER_SCHEMA, sequence, run_id, created_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = (json.dumps(record.wire(), ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with path.open("ab") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return record


def _tail_lines(path: Path, limit: int) -> list[bytes]:
    if limit < 1:
        return []
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return []
    if size == 0:
        return []
    with path.open("rb") as handle:
        position = size
        blob = b""
        while position and blob.count(b"\n") <= limit:
            step = min(position, 64 * 1024)
            position -= step
            handle.seek(position)
            blob = handle.read(step) + blob
        lines = blob.split(b"\n")
        # ``split`` produces an empty line after a normal trailing newline.
        if lines and lines[-1] == b"":
            lines.pop()
        return lines[-limit:]


def _stream_lines(path: Path) -> Iterator[bytes]:
    try:
        with path.open("rb") as handle:
            for line in handle:
                yield line.rstrip(b"\n")
    except FileNotFoundError:
        return


def _warning(code: str, checked: dict[str, Any], *, count: int = 1, examples: list[Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "code": code,
        "checked": checked,
        "count": count,
        "manual": MANUAL_PATH,
    }
    if examples:
        result["examples"] = examples[:_MAX_WARNING_EXAMPLES]
    return result


def read_dispatches(
    working_dir: Path | str,
    *,
    limit: int = _DEFAULT_TAIL,
    full_history: bool = False,
) -> LedgerRead:
    """Read append order and advisory integrity diagnostics without mutation."""
    path = ledger_path(working_dir)
    lines = list(_stream_lines(path)) if full_history else _tail_lines(path, limit)
    checked: dict[str, Any] = {
        "source": "full_ledger" if full_history else "tail",
        "requested_limit": None if full_history else limit,
        "records_read": len(lines),
        "sequence_from": None,
        "sequence_to": None,
    }
    if not lines:
        return LedgerRead((), (_warning("dispatch_ledger_empty", checked, count=0),), checked)

    records: list[DispatchRecord] = []
    invalid: list[int] = []
    for offset, raw in enumerate(lines):
        try:
            records.append(_parse_record(raw))
        except DispatchLedgerError:
            invalid.append(offset)
    if records:
        checked["sequence_from"] = records[0].sequence
        checked["sequence_to"] = records[-1].sequence
    warnings: list[dict[str, Any]] = []
    if invalid:
        warnings.append(_warning("dispatch_ledger_invalid_record", checked, count=len(invalid), examples=invalid))
    gaps: list[str] = []
    duplicates: list[str] = []
    prior: int | None = None
    seen: set[str] = set()
    for record in records:
        if prior is not None and record.sequence != prior + 1:
            gaps.append(str(record.sequence))
        prior = record.sequence
        if record.run_id in seen:
            duplicates.append(record.run_id)
        seen.add(record.run_id)
    if gaps:
        warnings.append(_warning("dispatch_ledger_sequence_non_monotonic", checked, count=len(gaps), examples=gaps))
    if duplicates:
        warnings.append(_warning("dispatch_ledger_duplicate_run_id", checked, count=len(duplicates), examples=duplicates))
    return LedgerRead(tuple(records), tuple(warnings), checked)


def read_recent_daemon_states(
    working_dir: Path | str,
    *,
    limit: int = _DEFAULT_TAIL,
    full_history: bool = False,
) -> tuple[LedgerRead, list[tuple[DispatchRecord, Path, dict[str, Any]]], list[dict[str, Any]]]:
    """Read only ledger-selected daemon state files and attach bounded warnings."""
    read = read_dispatches(working_dir, limit=limit, full_history=full_history)
    rows: list[tuple[DispatchRecord, Path, dict[str, Any]]] = []
    bad: list[str] = []
    for record in read.records:
        path = daemons_dir(working_dir) / record.run_id / "daemon.json"
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("not object")
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            bad.append(record.run_id)
            continue
        rows.append((record, path.parent, state))
    warnings = list(read.warnings)
    if bad:
        warnings.append(_warning("dispatch_ledger_daemon_state_unreadable", read.checked, count=len(bad), examples=bad))
    return read, rows, warnings


def _write_marker(working_dir: Path | str, kind: str, run_id: str, *, sequence: int | None = None) -> None:
    target = _marker_path(working_dir, kind, run_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {"schema": "lingtai.daemon_dispatch_recovery/v1", "kind": kind, "run_id": run_id}
    if sequence is not None:
        payload["sequence"] = sequence
    atomic_write_json(target, payload, ensure_ascii=False, indent=2)


def mark_running(working_dir: Path | str, run_id: str, *, sequence: int | None = None) -> None:
    _write_marker(working_dir, "running", run_id, sequence=sequence)


def mark_pending_terminal_notification(working_dir: Path | str, run_id: str, *, sequence: int | None = None) -> None:
    _write_marker(working_dir, "pending-terminal", run_id, sequence=sequence)


def clear_marker(working_dir: Path | str, kind: str, run_id: str) -> None:
    try:
        _marker_path(working_dir, kind, run_id).unlink()
    except FileNotFoundError:
        pass


def recovery_markers(working_dir: Path | str) -> list[tuple[str, str, Path]]:
    """Return only unresolved marker files; never enumerate lifetime run dirs."""
    root = recovery_dir(working_dir)
    try:
        paths = list(root.glob("*.json"))
    except OSError:
        return []
    rows: list[tuple[str, str, Path]] = []
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            kind = payload.get("kind") if isinstance(payload, dict) else None
            run_id = payload.get("run_id") if isinstance(payload, dict) else None
            if kind in {"running", "pending-terminal"} and isinstance(run_id, str) and run_id:
                rows.append((kind, run_id, path))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    return rows


__all__ = [
    "DispatchLedgerError", "DispatchRecord", "LedgerRead", "LEDGER_SCHEMA", "MANUAL_PATH",
    "append_dispatch", "clear_marker", "daemons_dir", "ledger_path", "mark_pending_terminal_notification",
    "mark_running", "read_dispatches", "read_recent_daemon_states", "recovery_markers",
]

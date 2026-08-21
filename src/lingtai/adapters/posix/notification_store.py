"""POSIX adapter for ``.notification/<channel>.json`` mirrors.

It provides atomic file replacement and Store-owned mutation serialization.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import re
import threading
from pathlib import Path

from lingtai.adapters.notification_store_lock import select_notification_store_lock
from lingtai.kernel._fsutil import atomic_write_json
from lingtai.kernel.notification_store import (
    AllowPredicate,
    CompareUpdateResult,
    ExpectedVersion,
    NotificationStorePort,
    PureAckMutator,
    PureCoreMutator,
    PureHookManifestMutator,
    UNCONDITIONAL,
    UpdateAckRefsResult,
    UpdateHookManifestsResult,
    _applied_result,
    _conflict_result,
)
from lingtai.kernel.notification_store._mutation_lock import (
    NotificationMutationLockPort,
)

_LARGE_RESULT_ACK_FILE = "large_result_acks.json"
_HOOK_REGISTRY_FILE = "hooks.json"
_DOT_NOTIFICATION = ".notification"
_DAEMON_CHANNEL = "daemon"
_DAEMON_DIR = "daemon"
_DAEMON_AGGREGATE_FILENAME = "daemon.json"
_DAEMON_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _notification_dir(workdir: Path) -> Path:
    """Return the canonical ``.notification/`` directory for a workdir."""
    return workdir / _DOT_NOTIFICATION


def _channel_path(workdir: Path, channel: str) -> Path:
    """Return the canonical path for one non-daemon channel mirror file."""
    return _notification_dir(workdir) / f"{channel}.json"


def _daemon_dir(workdir: Path) -> Path:
    """Return the directory containing daemon mini-channel files."""
    return _notification_dir(workdir) / _DAEMON_DIR


def _validate_daemon_id(daemon_id: str) -> str:
    """Validate a daemon id before using it as a mini-channel filename."""
    if not isinstance(daemon_id, str) or _DAEMON_ID_RE.fullmatch(daemon_id) is None:
        raise ValueError("daemon_id must match ^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    if ".." in daemon_id:
        raise ValueError("daemon_id must not contain '..'")
    return daemon_id


def _daemon_report_path(workdir: Path) -> Path:
    """Return the non-event aggregate report path."""
    return _notification_dir(workdir) / _DAEMON_AGGREGATE_FILENAME


def _daemon_path(workdir: Path, daemon_id: str) -> Path:
    return _daemon_dir(workdir) / f"{_validate_daemon_id(daemon_id)}.json"


def _daemon_id_from_payload(payload: object) -> str | None:
    """Extract the owning daemon id carried by a typed channel mutation.

    Every daemon event write must carry its run id.  An absent marker is not a
    compatibility request for the root report: callers must fail closed rather
    than create a competing event source.
    """
    if isinstance(payload, dict):
        direct = payload.get("daemon_id")
        if isinstance(direct, str) and direct:
            return _validate_daemon_id(direct)
        data = payload.get("data")
        if isinstance(data, dict):
            direct = data.get("daemon_id")
            if isinstance(direct, str) and direct:
                return _validate_daemon_id(direct)
    return None


def _daemon_files(workdir: Path) -> list[Path]:
    directory = _daemon_dir(workdir)
    if not directory.is_dir():
        return []
    return sorted(
        (path for path in directory.iterdir() if path.is_file() and path.suffix == ".json"),
        key=lambda path: path.name,
    )


def _daemon_records(workdir: Path) -> list[Path]:
    """Return only canonical per-daemon event files in deterministic order."""
    return _daemon_files(workdir)


def _read_daemon_payloads(workdir: Path) -> list[tuple[Path, bytes, dict]]:
    """Read valid canonical mini-channel files in deterministic order."""
    payloads: list[tuple[Path, bytes, dict]] = []
    for path in _daemon_records(workdir):
        try:
            raw = path.read_bytes()
            payload = json.loads(raw)
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            payloads.append((path, raw, payload))
    return payloads


def _daemon_events(payload: object) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    events = data.get("events") if isinstance(data, dict) else None
    return [event for event in events if isinstance(event, dict)] if isinstance(events, list) else []


def _configured_daemon_alarm_threshold(workdir: Path) -> int | None:
    """Read the optional daemon attention threshold for aggregate projection."""
    try:
        config = json.loads((workdir / "notification.json").read_text(encoding="utf-8"))
        value = config["channels"][_DAEMON_CHANNEL]["alarm_threshold"]
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _aggregate_daemon_payload(workdir: Path) -> dict | None:
    """Build the parent-visible event aggregate from canonical mini-files."""
    records = _read_daemon_payloads(workdir)
    if not records:
        return None
    events: list[dict] = []
    template = records[0][2]
    alarm_fired = False
    for _, _, payload in records:
        events.extend(_daemon_events(payload))
        data = payload.get("data")
        state = data.get(_DAEMON_CHANNEL) if isinstance(data, dict) else None
        alarm_fired = alarm_fired or (
            isinstance(state, dict) and state.get("alarm_fired") is True
        )
    # Preserve append order within each mini-file while giving independent
    # daemon files a deterministic order for snapshots and CAS tokens.
    data = {"events": events}
    threshold = _configured_daemon_alarm_threshold(workdir)
    data[_DAEMON_CHANNEL] = {
        "count": len(events),
        "alarm_fired": alarm_fired or (
            threshold is not None and len(events) > threshold
        ),
    }
    aggregate = dict(template)
    aggregate["header"] = f"{len(events)} daemon notification{'s' if len(events) != 1 else ''}"
    aggregate["data"] = data
    return aggregate


def _daemon_fingerprint(workdir: Path) -> tuple[str, int, str] | None:
    """Return one synthetic version covering every canonical mini-file byte."""
    records: list[tuple[str, bytes]] = []
    for path in _daemon_records(workdir):
        try:
            records.append(("mini/" + path.name, path.read_bytes()))
        except OSError:
            continue
    if not records:
        return None
    material = b"".join(
        name.encode("utf-8") + b"\\0" + str(len(raw)).encode("ascii") + b"\\0" + raw
        for name, raw in records
    )
    return (_DAEMON_AGGREGATE_FILENAME, len(material), hashlib.sha256(material).hexdigest())


def _daemon_report_payload(workdir: Path) -> dict:
    """Build the root report from mini-file stats, never from root events."""
    records = _read_daemon_payloads(workdir)
    runs: list[dict] = []
    total_events = 0
    active_runs = 0
    terminal_runs = 0
    terminal_states = {"done", "failed", "cancelled", "timeout"}
    for path, _, payload in records:
        data = payload.get("data")
        events = _daemon_events(payload)
        state = payload.get("state")
        if not isinstance(state, str) and isinstance(data, dict):
            state = data.get("state") or data.get("run_state")
        if not isinstance(state, str) and events:
            candidate = events[-1].get("status")
            state = candidate if isinstance(candidate, str) else None
        total_events += len(events)
        if state in terminal_states:
            terminal_runs += 1
        elif state:
            active_runs += 1
        run = {"daemon_id": path.stem, "event_count": len(events)}
        if state:
            run["state"] = state
        runs.append(run)
    report = {
        "kind": "daemon_report",
        "version": 1,
        "stats": {
            "run_count": len(runs),
            "event_count": total_events,
            "active_run_count": active_runs,
            "terminal_run_count": terminal_runs,
        },
        "runs": runs,
    }
    report_path = _daemon_report_path(workdir)
    try:
        raw = report_path.read_bytes()
    except FileNotFoundError:
        return report
    except OSError:
        return report
    try:
        previous = json.loads(raw)
    except json.JSONDecodeError:
        previous = None
    if isinstance(previous, dict) and previous.get("kind") == "daemon_report":
        migration = previous.get("migration")
        if isinstance(migration, dict):
            report["migration"] = migration
    elif previous is not None:
        report["migration"] = {"legacy_root": previous}
    else:
        report["migration"] = {
            "legacy_root_raw_base64": base64.b64encode(raw).decode("ascii")
        }
    return report


def _write_daemon_report(workdir: Path) -> None:
    """Persist the root aggregate report after a mini-file mutation."""
    report_path = _daemon_report_path(workdir)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        report_path, _daemon_report_payload(workdir), ensure_ascii=False, indent=None
    )


def _ack_path(workdir: Path) -> Path:
    return _notification_dir(workdir) / _LARGE_RESULT_ACK_FILE


def _hook_registry_path(workdir: Path) -> Path:
    return _notification_dir(workdir) / _HOOK_REGISTRY_FILE


def _version_entry(path: Path, raw: bytes) -> list:
    """Build one fingerprint entry from bytes already read successfully."""
    return [path.name, len(raw), hashlib.sha256(raw).hexdigest()]


def _safe_version(entry: list | tuple | None) -> list | None:
    """Return a JSON/log-safe fingerprint representation."""
    if entry is None:
        return None
    return list(entry)


class PosixNotificationStoreAdapter(NotificationStorePort):
    """Filesystem implementation of the Core-owned Store Port.

    One composed instance owns serialization; Core supplies channel policy.
    """

    def __init__(
        self,
        workdir: Path,
        mutation_lock: NotificationMutationLockPort | None = None,
    ):
        self._workdir = Path(workdir)
        self._lock = threading.Lock()
        self._mutation_lock = mutation_lock or select_notification_store_lock()

    @contextlib.contextmanager
    def _exclusive_mutation(self):
        # The thread lock prevents same-process lock re-entry while the native
        # lock serializes independently composed producer/supervisor processes.
        with self._lock:
            with self._mutation_lock.exclusive(_notification_dir(self._workdir)):
                yield

    def snapshot(self, allow_channel: AllowPredicate) -> dict[str, object]:
        notif_dir = _notification_dir(self._workdir)
        if not notif_dir.is_dir():
            return {}
        out: dict[str, object] = {}
        # Daemon is the one aggregate model-visible channel whose storage is a
        # directory of independent mini-channels. The sibling daemon.json is a
        # report only and is deliberately never read here.
        if allow_channel(_DAEMON_CHANNEL):
            aggregate = _aggregate_daemon_payload(self._workdir)
            if aggregate is not None:
                out[_DAEMON_CHANNEL] = aggregate
        for f in sorted(notif_dir.glob("*.json")):
            if f.name in {_LARGE_RESULT_ACK_FILE, _HOOK_REGISTRY_FILE, _DAEMON_AGGREGATE_FILENAME}:
                continue
            if not allow_channel(f.stem):
                continue
            try:
                out[f.stem] = json.loads(f.read_bytes())
            except (json.JSONDecodeError, OSError):
                continue
        return out


    def fingerprint(
        self, allow_channel: AllowPredicate
    ) -> tuple[tuple[str, int, str], ...]:
        notif_dir = _notification_dir(self._workdir)
        if not notif_dir.is_dir():
            return ()
        entries: list[tuple[str, int, str]] = []
        daemon_entry = _daemon_fingerprint(self._workdir) if allow_channel(_DAEMON_CHANNEL) else None
        if daemon_entry is not None:
            entries.append(daemon_entry)
        for f in notif_dir.iterdir():
            if not (f.is_file() and f.suffix == ".json"):
                continue
            if f.name in {_LARGE_RESULT_ACK_FILE, _HOOK_REGISTRY_FILE, _DAEMON_AGGREGATE_FILENAME}:
                continue
            if not allow_channel(f.stem):
                continue
            try:
                data = f.read_bytes()
            except OSError:
                continue
            entries.append((f.name, len(data), hashlib.sha256(data).hexdigest()))
        return tuple(sorted(entries))


    def publish(self, channel: str, payload: dict) -> None:
        if channel == _DAEMON_CHANNEL:
            daemon_id = _daemon_id_from_payload(payload)
            if daemon_id is None:
                raise ValueError("daemon event publish requires a daemon_id")
            target = _daemon_path(self._workdir, daemon_id)
        else:
            target = _channel_path(self._workdir, channel)
        with self._exclusive_mutation():
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(target, payload, ensure_ascii=False, indent=None)
            if channel == _DAEMON_CHANNEL:
                _write_daemon_report(self._workdir)


    def clear(self, channel: str) -> bool:
        with self._exclusive_mutation():
            targets = _daemon_records(self._workdir) if channel == _DAEMON_CHANNEL else [_channel_path(self._workdir, channel)]
            existed = False
            for target in targets:
                try:
                    target.unlink()
                    existed = True
                except FileNotFoundError:
                    continue
            if channel == _DAEMON_CHANNEL and existed:
                _write_daemon_report(self._workdir)
            return existed


    def _compare_update_daemon_aggregate(
        self,
        expected_version: ExpectedVersion,
        pure_core_mutator: PureCoreMutator,
    ) -> CompareUpdateResult:
        """Apply daemon policy through the existing typed channel family.

        Core mutators see the aggregate projection.  An append carries its run
        id in ``data.daemon_id``; this adapter-only routing detail lets the
        existing ``compare_update_channel`` Port operation disaggregate the new
        event into one mini-file without exposing a ninth Core operation.  A
        removal instead identifies removed event ids and unlinks only the
        corresponding mini-file.
        """
        current_payload = _aggregate_daemon_payload(self._workdir) or {}
        current_entry = _daemon_fingerprint(self._workdir)
        current_version = list(current_entry) if current_entry is not None else None
        if expected_version is not UNCONDITIONAL and _safe_version(expected_version) != current_version:
            return _conflict_result(
                expected_version=expected_version,
                current_version=current_version,
            )

        new_payload, new_changed, policy_value = pure_core_mutator(dict(current_payload))
        if not new_changed:
            return _applied_result(
                changed=False,
                cleared=False,
                value=policy_value,
                current_version=current_version,
                previous_version=current_version,
            )
        previous_version = current_version

        if new_payload is None:
            changed = False
            for target in _daemon_records(self._workdir):
                try:
                    target.unlink()
                    changed = True
                except FileNotFoundError:
                    continue
            if changed:
                _write_daemon_report(self._workdir)
            new_entry = _daemon_fingerprint(self._workdir)
            return _applied_result(
                changed=changed,
                cleared=new_entry is None,
                value=policy_value,
                current_version=list(new_entry) if new_entry is not None else None,
                previous_version=previous_version,
            )

        current_events = _daemon_events(current_payload)
        new_events = _daemon_events(new_payload)
        current_ids = {
            event.get("event_id") for event in current_events if event.get("event_id")
        }
        new_ids = {
            event.get("event_id") for event in new_events if event.get("event_id")
        }
        removed_ids = current_ids - new_ids
        # Compare event records as a multiset for compatibility with older
        # mini-file entries, while using event ids whenever present for
        # unambiguous run-file routing.
        remaining_new_events = list(new_events)
        removed_events: list[dict] = []
        for event in current_events:
            try:
                remaining_new_events.remove(event)
            except ValueError:
                removed_events.append(event)
        removed_without_id = [event for event in removed_events if not event.get("event_id")]

        def _is_removed(event: dict) -> bool:
            event_id = event.get("event_id")
            return bool(
                (event_id and event_id in removed_ids)
                or (not event_id and event in removed_without_id)
            )

        daemon_id = _daemon_id_from_payload(new_payload)
        changed = False

        if daemon_id is not None:
            added_events = [
                event for event in new_events
                if event.get("event_id") and event.get("event_id") not in current_ids
            ]
            if added_events:
                target = _daemon_path(self._workdir, daemon_id)
                target_payload: dict = {}
                try:
                    parsed = json.loads(target.read_bytes())
                    if isinstance(parsed, dict):
                        target_payload = parsed
                except (FileNotFoundError, OSError, json.JSONDecodeError):
                    target_payload = {}
                target_events = _daemon_events(target_payload) + added_events
                target_data = dict(new_payload.get("data", {}))
                target_data["events"] = target_events
                target_data["daemon_id"] = daemon_id
                target_payload = dict(new_payload)
                target_payload["data"] = target_data
                target_payload["header"] = (
                    f"{len(target_events)} daemon notification"
                    f"{'s' if len(target_events) != 1 else ''}"
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_json(target, target_payload, ensure_ascii=False, indent=None)
                changed = True
        elif removed_events:
            for path, _, payload in _read_daemon_payloads(self._workdir):
                events = _daemon_events(payload)
                if not any(_is_removed(event) for event in events):
                    continue
                # A daemon event/ref dismissal owns the entire run file; never
                # unlink a different or newer run's mini-channel.
                try:
                    path.unlink()
                    changed = True
                except FileNotFoundError:
                    pass

        elif new_changed:
            # An event mutation without a run marker has no canonical target.
            # Never fall back to the root report as an event store.
            raise ValueError("daemon event mutation requires a daemon_id")

        if changed:
            _write_daemon_report(self._workdir)

        # A daemon aggregate is never blindly rewritten: only an identified
        # append or an event/ref removal may change physical storage.
        new_entry = _daemon_fingerprint(self._workdir)
        return _applied_result(
            changed=changed,
            cleared=new_entry is None,
            value=policy_value,
            current_version=list(new_entry) if new_entry is not None else None,
            previous_version=previous_version,
        )


    def compare_update_channel(
        self,
        channel: str,
        expected_version: ExpectedVersion,
        pure_core_mutator: PureCoreMutator,
    ) -> CompareUpdateResult:
        if channel == _DAEMON_CHANNEL:
            with self._exclusive_mutation():
                return self._compare_update_daemon_aggregate(
                    expected_version, pure_core_mutator
                )
        target = _channel_path(self._workdir, channel)

        with self._exclusive_mutation():
            current_payload: dict = {}
            current_version: list | None = None
            try:
                raw_bytes = target.read_bytes()
            except FileNotFoundError:
                raw_bytes = None
            if raw_bytes is not None:
                current_version = _version_entry(target, raw_bytes)
                try:
                    parsed = json.loads(raw_bytes)
                    current_payload = parsed if isinstance(parsed, dict) else {}
                except json.JSONDecodeError:
                    current_payload = {}

            if expected_version is not UNCONDITIONAL:
                if expected_version is None:
                    if current_version is not None:
                        return _conflict_result(
                            expected_version=expected_version,
                            current_version=_safe_version(current_version),
                        )
                else:
                    expected_list = _safe_version(expected_version)
                    current_list = _safe_version(current_version)
                    if current_list != expected_list:
                        return _conflict_result(
                            expected_version=expected_list,
                            current_version=current_list,
                        )

            new_payload, new_changed, policy_value = pure_core_mutator(
                dict(current_payload) if isinstance(current_payload, dict) else {}
            )

            if not new_changed:
                return _applied_result(
                    changed=False,
                    cleared=False,
                    value=policy_value,
                    current_version=_safe_version(current_version),
                    previous_version=_safe_version(current_version),
                )

            previous_version = _safe_version(current_version)

            if new_payload is None:
                try:
                    target.unlink()
                    did_clear = True
                except FileNotFoundError:
                    did_clear = False
                return _applied_result(
                    changed=did_clear,
                    cleared=did_clear,
                    value=policy_value,
                    current_version=None,
                    previous_version=previous_version,
                )

            notif_dir = _notification_dir(self._workdir)
            notif_dir.mkdir(exist_ok=True)
            atomic_write_json(
                target, new_payload, ensure_ascii=False, indent=None
            )

            new_raw = target.read_bytes()
            new_version = _version_entry(target, new_raw)
            return _applied_result(
                changed=True,
                cleared=False,
                value=policy_value,
                current_version=_safe_version(new_version),
                previous_version=previous_version,
            )


    def load_ack_refs(self) -> set[str]:
        ack_path = _ack_path(self._workdir)
        try:
            data = json.loads(ack_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return {r for r in data if isinstance(r, str)}
        except (json.JSONDecodeError, OSError):
            pass
        return set()

    def update_ack_refs(
        self, pure_core_set_mutator: PureAckMutator
    ) -> UpdateAckRefsResult:
        ack_path = _ack_path(self._workdir)
        with self._exclusive_mutation():
            current = self.load_ack_refs()
            refs, requested_change, value = pure_core_set_mutator(set(current))
            if not requested_change:
                return UpdateAckRefsResult(changed=False, value=value)
            if not refs:
                try:
                    ack_path.unlink()
                    changed = True
                except OSError:
                    changed = False
                return UpdateAckRefsResult(changed=changed, value=value)
            ack_path.parent.mkdir(exist_ok=True)
            atomic_write_json(
                ack_path, sorted(refs), ensure_ascii=False, indent=None
            )
            return UpdateAckRefsResult(changed=True, value=value)

    def load_hook_manifests(self) -> list[dict]:
        """Return the persisted hook manifests, or ``[]`` when the registry
        is absent. A corrupt (invalid JSON) or unreadable registry raises so
        the tool layer can surface a structured ``hook_registry_load_failed``
        error instead of masquerading as "nothing registered"."""
        registry_path = _hook_registry_path(self._workdir)
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        if isinstance(data, list):
            return [m for m in data if isinstance(m, dict)]
        return []

    def stat_hook_registry(self) -> tuple[int, int] | None:
        registry_path = _hook_registry_path(self._workdir)
        try:
            st = registry_path.stat()
            return (st.st_mtime_ns, st.st_size)
        except OSError:
            return None

    def update_hook_manifests(
        self, pure_core_manifest_mutator: PureHookManifestMutator
    ) -> UpdateHookManifestsResult:
        registry_path = _hook_registry_path(self._workdir)
        with self._exclusive_mutation():
            current = self.load_hook_manifests()
            manifests, requested_change, value = pure_core_manifest_mutator(
                list(current)
            )
            if not requested_change:
                return UpdateHookManifestsResult(changed=False, value=value)
            if not manifests:
                try:
                    registry_path.unlink()
                    changed = True
                except OSError:
                    changed = False
                return UpdateHookManifestsResult(changed=changed, value=value)
            registry_path.parent.mkdir(exist_ok=True)
            atomic_write_json(
                registry_path, manifests, ensure_ascii=False, indent=None
            )
            return UpdateHookManifestsResult(changed=True, value=value)

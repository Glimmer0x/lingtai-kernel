"""Regression tests for inbound WeChat message replay after worker-hang refresh.

Bug: after an LLM worker hangs for 300s, the kernel refreshes via the
``chat_history_save_skipped`` path and relaunches without committing the
WeChat ``get_updates`` cursor. The iLink server then re-delivers the same
backlog, which used to land as brand-new inbox entries with fresh local UUIDs
and counted as new unread — polluting unread/notification state. These tests
pin the idempotency guard that suppresses such replays while preserving
genuinely new messages.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from lingtai.mcp_servers.wechat import manager as wechat_manager_module
from lingtai.mcp_servers.wechat.lockfile import PollerLockBusy
from lingtai.mcp_servers.wechat.manager import WechatManager
from lingtai.mcp_servers.wechat.types import (
    MessageItem, MessageItemType, TextItem, WeixinMessage,
)


def _manager(
    tmp_path: Path, events: list[dict] | None = None, *, on_inbound=None,
) -> WechatManager:
    return WechatManager(
        token="test-token",
        user_id="test-bot",
        working_dir=tmp_path,
        on_inbound=on_inbound if on_inbound is not None else (
            events.append if events is not None else None
        ),
    )


def _text_msg(
    *,
    from_user: str,
    text: str,
    message_id: int | None = None,
    seq: int | None = None,
    item_msg_id: str | None = None,
    create_time_ms: int | None = None,
) -> WeixinMessage:
    """Build a USER (type=1) text WeixinMessage as msg_from_dict would."""
    return WeixinMessage(
        seq=seq,
        message_id=message_id,
        from_user_id=from_user,
        message_type=1,
        create_time_ms=create_time_ms,
        item_list=[
            MessageItem(
                type=MessageItemType.TEXT,
                msg_id=item_msg_id,
                text_item=TextItem(text=text),
            )
        ],
    )


def _inbox_count(tmp_path: Path) -> int:
    inbox = tmp_path / "wechat" / "inbox"
    return sum(1 for d in inbox.iterdir() if (d / "message.json").is_file())


def _deliver(mgr: WechatManager, msg: WeixinMessage) -> None:
    asyncio.run(mgr._on_incoming(msg))


class _FakeAccountLock:
    def __init__(self, *, busy: bool = False) -> None:
        self.busy = busy
        self.acquire_calls = 0
        self.release_calls = 0
        self.owned = False
        self.path = Path("fake-wechat-lock")

    def acquire(self) -> None:
        self.acquire_calls += 1
        if self.busy:
            raise PollerLockBusy("fake lock busy")
        self.owned = True

    def release(self) -> None:
        self.release_calls += 1
        self.owned = False


class _InlineThread:
    """Run the patched no-network poll target without creating a real thread."""

    def __init__(self, *, target, args, daemon, name) -> None:
        self._target = target
        self._args = args

    def start(self) -> None:
        self._target(*self._args)

    def join(self, timeout=None) -> None:
        return None


def _start_without_network(
    mgr: WechatManager, monkeypatch, lock: _FakeAccountLock | None = None,
) -> _FakeAccountLock:
    fake_lock = lock or _FakeAccountLock()
    monkeypatch.setattr(mgr, "_account_lock", fake_lock)

    async def no_poll() -> None:
        return None

    monkeypatch.setattr(mgr, "_poll_loop", no_poll)
    monkeypatch.setattr(
        mgr, "write_identity_file", lambda: mgr._working_dir / "wechat.identity.json",
    )
    monkeypatch.setattr(wechat_manager_module.threading, "Thread", _InlineThread)
    mgr.start()
    return fake_lock


@pytest.mark.parametrize(
    "failure", ["drain", "new_event_loop", "thread_constructor", "thread_start"],
)
def test_start_setup_failure_rolls_back_lock_and_runtime_state(
    tmp_path, monkeypatch, failure,
):
    """Every post-lock setup failure releases ownership and closes its loop."""
    mgr = _manager(tmp_path, [])
    lock = _FakeAccountLock()
    monkeypatch.setattr(mgr, "_account_lock", lock)

    loops = []
    real_new_event_loop = wechat_manager_module.asyncio.new_event_loop

    def tracked_new_event_loop():
        loop = real_new_event_loop()
        loops.append(loop)
        return loop

    if failure == "drain":
        def fail_drain():
            raise RuntimeError("drain failed")

        monkeypatch.setattr(mgr, "_drain_pending_callbacks", fail_drain)
    elif failure == "new_event_loop":
        def fail_new_event_loop():
            raise RuntimeError("new loop failed")

        monkeypatch.setattr(
            wechat_manager_module.asyncio, "new_event_loop", fail_new_event_loop,
        )
    else:
        monkeypatch.setattr(
            wechat_manager_module.asyncio, "new_event_loop", tracked_new_event_loop,
        )
        if failure == "thread_constructor":
            def fail_thread(*args, **kwargs):
                raise RuntimeError("thread construction failed")

            monkeypatch.setattr(
                wechat_manager_module.threading, "Thread", fail_thread,
            )
        else:
            class FailingThread:
                def __init__(self, **kwargs):
                    self.kwargs = kwargs

                def start(self):
                    raise RuntimeError("thread start failed")

            monkeypatch.setattr(
                wechat_manager_module.threading, "Thread", FailingThread,
            )

    with pytest.raises(RuntimeError, match="failed"):
        mgr.start()

    assert lock.acquire_calls == 1
    assert lock.release_calls == 1
    assert lock.owned is False
    assert mgr._running is False
    assert mgr._loop is None
    assert mgr._poll_thread is None
    assert all(loop.is_closed() for loop in loops)


# ── Replay suppression (the bug) ──────────────────────────────────────────

def test_replay_same_upstream_id_lands_once(tmp_path):
    """Same upstream message_id re-delivered with a new fetch lands ONCE
    and wakes the host ONCE, even though the local UUID would differ."""
    events: list[dict] = []
    mgr = _manager(tmp_path, events)
    user = "wxid_alice@im.wechat"

    first = _text_msg(from_user=user, text="hi", message_id=12345)
    # Replay: identical upstream id, distinct WeixinMessage object (the
    # addon never sees the old local UUID, only the upstream payload).
    replay = _text_msg(from_user=user, text="hi", message_id=12345)

    _deliver(mgr, first)
    _deliver(mgr, replay)

    assert _inbox_count(tmp_path) == 1, "replay must not create a 2nd inbox entry"
    assert len(events) == 1, "replay must not trigger a 2nd LICC wake"


def test_replay_falls_back_to_content_signature(tmp_path):
    """When upstream omits message_id/seq/item msg_id, dedup falls back to
    (from_user, create_time_ms, body_hash) — same content + same upstream
    send time is a replay even though the local landing date differs."""
    events: list[dict] = []
    mgr = _manager(tmp_path, events)
    user = "wxid_bob@im.wechat"

    first = _text_msg(from_user=user, text="status?", create_time_ms=1_700_000_000_000)
    replay = _text_msg(from_user=user, text="status?", create_time_ms=1_700_000_000_000)

    _deliver(mgr, first)
    _deliver(mgr, replay)

    assert _inbox_count(tmp_path) == 1
    assert len(events) == 1


def test_replay_survives_relaunch_via_persisted_index(tmp_path):
    """The guard is durable: a fresh manager (simulating refresh+relaunch)
    loads inbox_seen.json and still suppresses the replay."""
    events1: list[dict] = []
    mgr1 = _manager(tmp_path, events1)
    user = "wxid_carol@im.wechat"
    _deliver(mgr1, _text_msg(from_user=user, text="ping", message_id=99))
    assert (tmp_path / "wechat" / "inbox_seen.json").is_file()

    # New manager instance == relaunch after refresh.
    events2: list[dict] = []
    mgr2 = _manager(tmp_path, events2)
    _deliver(mgr2, _text_msg(from_user=user, text="ping", message_id=99))

    assert _inbox_count(tmp_path) == 1
    assert events2 == [], "replay after relaunch must not re-wake the host"


def test_constructor_does_not_publish_until_owned_start_recovers_pending(
    tmp_path, monkeypatch,
):
    """Constructor is inert; start drains only after fake lock ownership."""
    user = "wxid_start@im.wechat"
    first = _manager(tmp_path, on_inbound=lambda _event: False)
    _deliver(first, _text_msg(from_user=user, text="startup", message_id=75310))

    lock = _FakeAccountLock()
    observed: list[tuple[bool, str]] = []

    def accepted(event: dict) -> None:
        observed.append((lock.owned, event["metadata"]["message_id"]))

    second = _manager(tmp_path, on_inbound=accepted)
    assert observed == []

    _start_without_network(second, monkeypatch, lock)
    assert observed == [(True, next(iter((tmp_path / "wechat" / "inbox").iterdir())).name)]
    assert lock.acquire_calls == 1
    assert lock.owned is True
    second.stop()
    assert lock.release_calls == 1
    assert lock.owned is False


def test_lock_busy_start_never_publishes_pending_callback(tmp_path, monkeypatch):
    user = "wxid_busy@im.wechat"
    first = _manager(tmp_path, on_inbound=lambda _event: False)
    _deliver(first, _text_msg(from_user=user, text="busy", message_id=75311))

    events: list[dict] = []
    second = _manager(tmp_path, events)
    lock = _FakeAccountLock(busy=True)
    monkeypatch.setattr(second, "_account_lock", lock)

    with pytest.raises(PollerLockBusy):
        second.start()
    assert events == []
    assert lock.acquire_calls == 1
    assert lock.release_calls == 0


def test_crash_after_first_record_write_recovers_same_uuid_on_start(
    tmp_path, monkeypatch,
):
    """The first durable callback record already carries pending state."""
    user = "wxid_crash@im.wechat"
    first_events: list[dict] = []
    first = _manager(
        tmp_path, on_inbound=lambda event: first_events.append(event),
    )

    def fail_before_seen(_key: str, _local_id: str) -> None:
        raise RuntimeError("simulated crash before seen barrier")

    monkeypatch.setattr(first, "_record_seen", fail_before_seen)
    with pytest.raises(RuntimeError, match="before seen"):
        _deliver(first, _text_msg(from_user=user, text="crash", message_id=75312))

    inbox = tmp_path / "wechat" / "inbox"
    dirs = [path for path in inbox.iterdir() if path.is_dir()]
    assert len(dirs) == 1
    local_id = dirs[0].name
    record = json.loads((dirs[0] / "message.json").read_text(encoding="utf-8"))
    assert record["id"] == local_id
    assert record["pending_publication"]["metadata"]["message_id"] == local_id
    assert first_events == []
    assert not (tmp_path / "wechat" / "inbox_seen.json").exists()

    recovered: list[dict] = []
    second = _manager(tmp_path, recovered)
    lock = _start_without_network(second, monkeypatch)
    assert len(recovered) == 1
    assert recovered[0]["metadata"]["message_id"] == local_id
    seen = json.loads((tmp_path / "wechat" / "inbox_seen.json").read_text())
    assert seen["keys"][record["stable_key"]] == local_id
    final = json.loads((dirs[0] / "message.json").read_text(encoding="utf-8"))
    assert "pending_publication" not in final
    assert len([path for path in inbox.iterdir() if (path / "message.json").is_file()]) == 1
    second.stop()
    assert lock.release_calls == 1


def test_same_manager_replay_retries_pending_without_second_uuid(tmp_path):
    user = "wxid_same_manager@im.wechat"
    attempts: list[tuple[str, bool | None]] = []
    outcomes = iter((False, None))

    def mutable(event: dict) -> bool | None:
        attempts.append((event["metadata"]["message_id"], next(outcomes)))
        return attempts[-1][1]

    mgr = _manager(tmp_path, on_inbound=mutable)
    msg = _text_msg(from_user=user, text="mutable", message_id=75313)
    _deliver(mgr, msg)
    inbox = tmp_path / "wechat" / "inbox"
    local_id = next(path.name for path in inbox.iterdir() if path.is_dir())
    _deliver(mgr, _text_msg(from_user=user, text="mutable", message_id=75313))

    assert attempts == [(local_id, False), (local_id, None)]
    assert _inbox_count(tmp_path) == 1
    final = json.loads((inbox / local_id / "message.json").read_text(encoding="utf-8"))
    assert "pending_publication" not in final


def test_mismatched_pending_and_seen_mapping_are_ignored(tmp_path, monkeypatch):
    user = "wxid_mismatch@im.wechat"
    first = _manager(tmp_path, on_inbound=lambda _event: False)
    _deliver(first, _text_msg(from_user=user, text="mismatch", message_id=75314))
    inbox = tmp_path / "wechat" / "inbox"
    msg_dir = next(path for path in inbox.iterdir() if path.is_dir())
    msg_file = msg_dir / "message.json"
    record = json.loads(msg_file.read_text(encoding="utf-8"))
    local_id = msg_dir.name
    stable_key = record["stable_key"]

    record["pending_publication"]["metadata"]["message_ref"] = "other-local-id"
    msg_file.write_text(json.dumps(record), encoding="utf-8")
    malformed_events: list[dict] = []
    malformed = _manager(tmp_path, malformed_events)
    malformed_lock = _start_without_network(malformed, monkeypatch)
    assert malformed_events == []
    malformed.stop()
    assert malformed_lock.release_calls == 1

    record["pending_publication"]["metadata"]["message_ref"] = local_id
    msg_file.write_text(json.dumps(record), encoding="utf-8")
    seen_file = tmp_path / "wechat" / "inbox_seen.json"
    seen = {"version": 1, "order": [stable_key], "keys": {stable_key: "different-id"}}
    seen_file.write_text(json.dumps(seen), encoding="utf-8")
    bounded_events: list[dict] = []
    bounded = _manager(tmp_path, bounded_events)
    lock = _start_without_network(bounded, monkeypatch)
    assert bounded_events == []
    bounded.stop()
    assert lock.release_calls == 1


# ── Genuine messages must NOT be dropped ──────────────────────────────────

@pytest.mark.parametrize(
    ("failure", "user", "upstream_id", "text"),
    [
        ("false", "wxid_false@im.wechat", 75301, "retry-false"),
        ("exception", "wxid_raise@im.wechat", 75302, "retry-raise"),
    ],
)
def test_callback_failure_is_retryable_after_fresh_manager_start(
    tmp_path, monkeypatch, failure, user, upstream_id, text,
):
    """False and exception results both retain and later retry one landing."""
    attempts: list[str] = []

    def rejected(event: dict) -> bool:
        attempts.append(event["metadata"]["message_id"])
        if failure == "exception":
            raise RuntimeError("test callback failure")
        return False

    mgr1 = _manager(
        tmp_path,
        on_inbound=rejected,
    )
    _deliver(mgr1, _text_msg(from_user=user, text=text, message_id=upstream_id))

    inbox_dir = tmp_path / "wechat" / "inbox"
    landed = json.loads(next(inbox_dir.iterdir()).joinpath("message.json").read_text())
    local_id = landed["id"]
    stable_key = landed["stable_key"]
    seen = json.loads((tmp_path / "wechat" / "inbox_seen.json").read_text())
    assert seen["keys"][stable_key] == local_id
    assert stable_key == f"{user}|mid:{upstream_id}"
    assert attempts == [local_id]
    assert landed["pending_publication"]["metadata"]["message_id"] == local_id

    retry_attempts: list[str] = []
    mgr2 = _manager(
        tmp_path,
        on_inbound=lambda event: retry_attempts.append(
            event["metadata"]["message_id"]
        ),
    )
    lock = _start_without_network(mgr2, monkeypatch)

    assert _inbox_count(tmp_path) == 1
    assert retry_attempts == [local_id]
    final_record = json.loads((inbox_dir / local_id / "message.json").read_text())
    assert "pending_publication" not in final_record
    mgr2.stop()
    assert lock.release_calls == 1



def test_public_surfaces_hide_pending_state(tmp_path):
    user = "wxid_private@im.wechat"
    mgr = _manager(tmp_path, on_inbound=lambda _event: False)
    _deliver(mgr, _text_msg(from_user=user, text="private", message_id=75315))
    local_id = next(
        path.name for path in (tmp_path / "wechat" / "inbox").iterdir()
        if path.is_dir()
    )

    public = [
        mgr.handle({"action": "check"}),
        mgr.handle({"action": "read", "user_id": user}),
        mgr.handle({"action": "search", "query": "private"}),
    ]
    serialized = json.dumps(public, ensure_ascii=False)
    assert "pending_publication" not in serialized
    assert local_id in serialized


@pytest.mark.parametrize("kind", ["malformed_json", "path_id", "mismatched_id"])
def test_pending_recovery_ignores_invalid_record_without_publication(
    tmp_path, monkeypatch, kind,
):
    """Startup recovery never publishes malformed or path-shaped local state."""
    first = _manager(tmp_path, on_inbound=lambda _event: False)
    _deliver(first, _text_msg(from_user="wxid_invalid@im.wechat", text="pending", message_id=75320))
    inbox_dir = tmp_path / "wechat" / "inbox"
    msg_dir = next(path for path in inbox_dir.iterdir() if path.is_dir())
    msg_file = msg_dir / "message.json"

    if kind == "malformed_json":
        msg_file.write_text("{not-json", encoding="utf-8")
    else:
        record = json.loads(msg_file.read_text(encoding="utf-8"))
        candidate = "../escape" if kind == "path_id" else "not-the-containing-dir"
        record["id"] = candidate
        record["pending_publication"]["metadata"]["message_id"] = candidate
        record["pending_publication"]["metadata"]["message_ref"] = candidate
        msg_file.write_text(json.dumps(record), encoding="utf-8")

    recovered: list[dict] = []
    second = _manager(tmp_path, recovered)
    lock = _start_without_network(second, monkeypatch)
    assert recovered == []
    assert not (tmp_path / "wechat" / "escape").exists()
    second.stop()
    assert lock.release_calls == 1


@pytest.mark.parametrize("kind", ["directory", "file"])
def test_pending_recovery_ignores_symlinked_message_path(
    tmp_path, monkeypatch, kind,
):
    """Recovery and public views skip symlinked message paths."""
    first = _manager(tmp_path, on_inbound=lambda _event: False)
    _deliver(first, _text_msg(from_user="wxid_symlink@im.wechat", text="pending", message_id=75321))
    inbox_dir = tmp_path / "wechat" / "inbox"
    msg_dir = next(path for path in inbox_dir.iterdir() if path.is_dir())
    msg_file = msg_dir / "message.json"

    try:
        if kind == "directory":
            target = tmp_path / "outside-pending"
            msg_dir.rename(target)
            msg_dir.symlink_to(target, target_is_directory=True)
            outside_file = target / "message.json"
        else:
            target = tmp_path / "outside-message.json"
            msg_file.rename(target)
            msg_file.symlink_to(target)
            outside_file = target
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlinks unavailable on this platform: {exc}")

    sentinel = {
        "id": "outside-sentinel",
        "from_user_id": "wxid_outside_sentinel@im.wechat",
        "body": "OUTSIDE_SENTINEL",
        "date": "2099-01-01T00:00:00+00:00",
    }
    outside_file.write_text(json.dumps(sentinel), encoding="utf-8")
    outside_content = outside_file.read_bytes()

    recovered: list[dict] = []
    second = _manager(tmp_path, recovered)
    lock = _start_without_network(second, monkeypatch)
    assert recovered == []

    assert second.handle({"action": "check"}) == {"conversations": []}
    assert second.handle({
        "action": "read", "user_id": sentinel["from_user_id"],
    }) == {"messages": []}
    assert second.handle({
        "action": "search", "query": "OUTSIDE_SENTINEL",
    }) == {"matches": []}

    second.stop()
    assert lock.release_calls == 1
    assert outside_file.exists()
    assert outside_file.read_bytes() == outside_content
    if kind == "directory":
        assert msg_dir.is_symlink()
    else:
        assert msg_file.is_symlink()


def test_corrupt_pending_marker_is_ignored_without_new_local_landing(tmp_path):
    """Malformed self-generated state never widens into a duplicate landing."""
    user = "wxid_corrupt@im.wechat"
    mgr1 = _manager(tmp_path, [])
    _deliver(mgr1, _text_msg(from_user=user, text="corrupt pending", message_id=75304))

    inbox_dir = tmp_path / "wechat" / "inbox"
    msg_dir = next(inbox_dir.iterdir())
    record = json.loads((msg_dir / "message.json").read_text())
    local_id = record["id"]
    record["pending_publication"] = {"unexpected": "shape"}
    (msg_dir / "message.json").write_text(json.dumps(record), encoding="utf-8")

    retried: list[dict] = []
    mgr2 = _manager(tmp_path, retried)
    _deliver(mgr2, _text_msg(from_user=user, text="corrupt pending", message_id=75304))

    assert retried == []
    assert _inbox_count(tmp_path) == 1
    assert next(inbox_dir.iterdir()).name == local_id


@pytest.mark.parametrize(
    ("first", "second"),
    [
        pytest.param(
            _text_msg(from_user="wxid_dave@im.wechat", text="ok", message_id=1),
            _text_msg(from_user="wxid_dave@im.wechat", text="ok", message_id=2),
            id="different-upstream-ids",
        ),
        pytest.param(
            _text_msg(
                from_user="wxid_erin@im.wechat", text="here",
                create_time_ms=1_700_000_000_000,
            ),
            _text_msg(
                from_user="wxid_erin@im.wechat", text="here",
                create_time_ms=1_700_000_060_000,
            ),
            id="different-create-times",
        ),
        pytest.param(
            _text_msg(from_user="wxid_a@im.wechat", text="yo", create_time_ms=42),
            _text_msg(from_user="wxid_b@im.wechat", text="yo", create_time_ms=42),
            id="different-senders",
        ),
    ],
)
def test_distinct_messages_both_land(tmp_path, first, second):
    """Distinct upstream identity dimensions never suppress a real message."""
    events: list[dict] = []
    mgr = _manager(tmp_path, events)
    _deliver(mgr, first)
    _deliver(mgr, second)
    assert _inbox_count(tmp_path) == 2
    assert len(events) == 2


# ── Provenance / traceability ─────────────────────────────────────────────

def test_landed_message_records_stable_key_provenance(tmp_path):
    """The landed message.json carries the stable_key + upstream ids so a
    suppressed duplicate is always traceable to its original (no silent loss)."""
    events: list[dict] = []
    mgr = _manager(tmp_path, events)
    user = "wxid_frank@im.wechat"
    _deliver(mgr, _text_msg(from_user=user, text="trace me", message_id=777,
                            create_time_ms=123))

    inbox = tmp_path / "wechat" / "inbox"
    msg_file = next(inbox.iterdir()) / "message.json"
    data = json.loads(msg_file.read_text(encoding="utf-8"))
    assert data["stable_key"] == f"{user}|mid:777"
    assert data["upstream_message_id"] == 777
    assert data["upstream_create_time_ms"] == 123

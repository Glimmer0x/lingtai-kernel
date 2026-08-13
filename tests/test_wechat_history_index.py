"""Regression coverage for bounded WeChat history views (issue #1375)."""
from __future__ import annotations

import json
from pathlib import Path

from lingtai.mcp_servers.wechat.manager import WechatManager


def _manager(tmp_path: Path) -> WechatManager:
    return WechatManager(
        token="test-token",
        user_id="test-bot",
        working_dir=tmp_path,
        on_inbound=lambda _event: None,
    )


def _write_message(
    tmp_path: Path,
    *,
    folder: str,
    message_id: str,
    peer: str,
    date: str,
) -> None:
    msg_dir = tmp_path / "wechat" / folder / message_id
    msg_dir.mkdir(parents=True)
    if folder == "inbox":
        record = {
            "id": message_id,
            "from_user_id": peer,
            "body": f"incoming {message_id}",
            "date": date,
        }
    else:
        record = {
            "id": message_id,
            "to_user_id": peer,
            "text": f"outgoing {message_id}",
            "date": date,
        }
    (msg_dir / "message.json").write_text(
        json.dumps(record), encoding="utf-8"
    )


def _message_json_reads(monkeypatch):
    reads = 0
    original = Path.read_text

    def counted(path: Path, *args, **kwargs):
        nonlocal reads
        if path.name == "message.json":
            reads += 1
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted)
    return lambda: reads


def test_bounded_views_do_not_rescan_retained_history(tmp_path: Path, monkeypatch) -> None:
    user = "wxid-alice"
    other = "wxid-other"
    for i in range(20):
        _write_message(
            tmp_path,
            folder="inbox",
            message_id=f"in-{i}",
            peer=user if i % 2 == 0 else other,
            date=f"2026-07-06T01:{i:02d}:00+00:00",
        )
        _write_message(
            tmp_path,
            folder="sent",
            message_id=f"out-{i}",
            peer=user if i % 2 == 0 else other,
            date=f"2026-07-06T02:{i:02d}:00+00:00",
        )

    # Manager startup performs the one-time index build. Routine operations
    # below are measured after that rebuild has completed.
    manager = _manager(tmp_path)
    read_count = _message_json_reads(monkeypatch)

    checked = manager._handle_check({})
    assert {item["user_id"] for item in checked["conversations"]} == {user, other}
    assert read_count() == 0

    read = manager._handle_read({"user_id": user, "limit": 1})
    assert len(read["messages"]) == 1
    assert read_count() == 1

    before_preview = read_count()
    _body, metadata = manager._build_conversation_preview_and_metadata(
        user, "current", max_messages=10
    )
    assert len(metadata["recent_messages"]) == 10
    assert read_count() - before_preview == 10


def test_corrupt_history_index_rebuilds_from_message_files(tmp_path: Path) -> None:
    user = "wxid-rebuild"
    _write_message(
        tmp_path,
        folder="inbox",
        message_id="in-1",
        peer=user,
        date="2026-07-06T01:00:00+00:00",
    )
    index = tmp_path / "wechat" / "history_index.json"
    index.write_text("{not json", encoding="utf-8")

    manager = _manager(tmp_path)

    conversations = manager._handle_check({})["conversations"]
    assert conversations == [
        {
            "user_id": user,
            "alias": user,
            "total": 1,
            "unread": 1,
            "latest": "incoming in-1",
            "date": "2026-07-06T01:00:00+00:00",
        }
    ]
    payload = json.loads(index.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert len(payload["entries"]) == 1

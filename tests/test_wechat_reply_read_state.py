"""Regression tests: WeChat reply() drains the unread counter.

Issue #715: replying to an incoming message never marked it read, so a chat
where the bot answered directly (without an explicit read) kept a positive
unread count forever. Replying handles the message and must mark it read,
mirroring the Telegram addon's reply handler.
"""
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


def _write_inbox(
    mgr: WechatManager, message_id: str, user_id: str = "human-1",
) -> None:
    msg_dir = mgr._inbox_dir / message_id
    msg_dir.mkdir(parents=True, exist_ok=True)
    (msg_dir / "message.json").write_text(
        json.dumps(
            {
                "id": message_id,
                "from_user_id": user_id,
                "text": "hello",
                "date": "2026-07-06T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )


def _conversations(mgr: WechatManager) -> list[dict]:
    return mgr._handle_check({})["conversations"]


def _unread_for_human(mgr: WechatManager) -> int:
    for conv in _conversations(mgr):
        if conv["alias"] == "human-1":
            return conv["unread"]
    return -1


def test_incoming_message_starts_unread(tmp_path: Path) -> None:
    mgr = _manager(tmp_path)
    _write_inbox(mgr, "msg-1")
    assert _unread_for_human(mgr) == 1


def test_reply_marks_original_message_read(tmp_path: Path, monkeypatch) -> None:
    mgr = _manager(tmp_path)
    _write_inbox(mgr, "msg-1")

    monkeypatch.setattr(
        mgr,
        "_handle_send",
        lambda args: {"status": "ok", "sent": ["text"], "message_id": "sent-1"},
    )
    result = mgr._handle_reply({"message_id": "msg-1", "text": "got it"})
    assert result["status"] == "ok"

    convs = _conversations(mgr)
    assert convs[0]["unread"] == 0
    assert convs[0]["total"] == 1


def test_reply_read_state_persists_across_restart(tmp_path: Path, monkeypatch) -> None:
    mgr = _manager(tmp_path)
    _write_inbox(mgr, "msg-1")

    monkeypatch.setattr(
        mgr,
        "_handle_send",
        lambda args: {"status": "ok", "sent": ["text"], "message_id": "sent-1"},
    )
    mgr._handle_reply({"message_id": "msg-1", "text": "got it"})

    # read.json is written: a fresh manager over the same dir still reports
    # the answered message as read.
    restarted = _manager(tmp_path)
    assert _unread_for_human(restarted) == 0


def test_failed_reply_does_not_mark_read(tmp_path: Path, monkeypatch) -> None:
    mgr = _manager(tmp_path)
    _write_inbox(mgr, "msg-1")

    monkeypatch.setattr(
        mgr,
        "_handle_send",
        lambda args: {"error": "send failed"},
    )
    result = mgr._handle_reply({"message_id": "msg-1", "text": "got it"})
    assert "error" in result
    assert _unread_for_human(mgr) == 1

"""Regression tests: Telegram check() unread counts incoming messages only.

Issue #715: the bot's own outgoing replies were counted as unread (merged
inbox + sent history against read_ids), so every reply inflated the counter
and a fully-handled chat never drained to zero. Unread must count incoming
messages only, matching the WeChat addon's documented rule.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lingtai.mcp_servers.telegram.manager import TelegramManager
from tests._notification_store_helpers import notification_store_for


class _FakeAccount:
    alias = "main"

    def send_message(self, chat_id: int, text: str, **_kwargs: Any) -> dict[str, Any]:
        return {"message_id": 9001, "chat": {"id": chat_id}, "text": text}

    def set_message_reaction(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def send_chat_action(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _FakeService:
    default_account = _FakeAccount()

    def get_account(self, _alias: str) -> _FakeAccount:
        return self.default_account

    def list_accounts(self) -> list[str]:
        return ["main"]


def _manager(workdir: Path) -> TelegramManager:
    return TelegramManager(
        _FakeService(),
        working_dir=workdir,
        on_inbound=lambda _event: None,
        notification_store=notification_store_for(workdir),
    )


def _write_inbox_message(
    workdir: Path,
    *,
    account: str = "main",
    chat_id: int = 123,
    message_id: int = 53,
    text: str = "hello",
) -> str:
    compound_id = f"{account}:{chat_id}:{message_id}"
    msg_dir = workdir / "telegram" / account / "inbox" / f"uuid-{chat_id}-{message_id}"
    msg_dir.mkdir(parents=True, exist_ok=True)
    (msg_dir / "message.json").write_text(
        json.dumps(
            {
                "id": compound_id,
                "from": {"username": "alice"},
                "chat": {"id": chat_id, "type": "private"},
                "date": f"2026-05-21T23:{message_id % 60:02d}:00Z",
                "text": text,
                "media": None,
                "callback_query": None,
                "reply_to_message_id": None,
            }
        ),
        encoding="utf-8",
    )
    return compound_id


def _write_sent_message(
    workdir: Path,
    *,
    account: str = "main",
    chat_id: int = 123,
    message_id: int = 9001,
    text: str = "my reply",
) -> str:
    compound_id = f"{account}:{chat_id}:{message_id}"
    msg_dir = workdir / "telegram" / account / "sent" / f"uuid-{chat_id}-{message_id}"
    msg_dir.mkdir(parents=True, exist_ok=True)
    (msg_dir / "message.json").write_text(
        json.dumps(
            {
                "id": compound_id,
                "to": {"chat_id": chat_id},
                "date": "2026-05-21T23:59:00Z",
                "text": text,
                "status": "sent",
            }
        ),
        encoding="utf-8",
    )
    return compound_id


def _chat_by_id(check_result: dict, chat_id: int) -> dict:
    return next(
        conv for conv in check_result["messages"] if conv["chat_id"] == chat_id
    )


def test_check_counts_only_incoming_messages_as_unread(tmp_path: Path) -> None:
    workdir = tmp_path / "agent"
    _write_inbox_message(workdir, message_id=53, text="question 1")
    _write_inbox_message(workdir, message_id=54, text="question 2")
    _write_sent_message(workdir, message_id=9001, text="answer 1")
    _write_sent_message(workdir, message_id=9002, text="answer 2")
    _write_sent_message(workdir, message_id=9003, text="answer 3")

    manager = _manager(workdir)
    check = manager._check({"account": "main"})

    conv = _chat_by_id(check, 123)
    # Total merges inbox + sent (post-molt visibility preserved) ...
    assert conv["total"] == 5
    # ... but unread reflects only the two incoming messages, not the three
    # outgoing replies the bot itself produced.
    assert conv["unread"] == 2


def test_check_reports_zero_unread_after_fully_read_chat(tmp_path: Path) -> None:
    workdir = tmp_path / "agent"
    _write_inbox_message(workdir, message_id=53, text="question 1")
    _write_inbox_message(workdir, message_id=54, text="question 2")
    _write_sent_message(workdir, message_id=9001, text="answer 1")

    manager = _manager(workdir)
    manager._read({"account": "main", "chat_id": 123, "limit": 10})

    conv = _chat_by_id(manager._check({"account": "main"}), 123)
    # A fully-handled chat drains to zero: the incoming messages were read and
    # the bot's own reply is never counted.
    assert conv["unread"] == 0
    assert conv["total"] == 3


def test_check_unread_drains_when_bot_replies_to_last_message(tmp_path: Path) -> None:
    """Headline #715 scenario: bot replied last, yet unread stayed positive."""
    workdir = tmp_path / "agent"
    compound_id = _write_inbox_message(workdir, message_id=53, text="question")

    manager = _manager(workdir)
    result = manager._reply({"account": "main", "message_id": compound_id, "text": "answer"})
    assert result["status"] == "sent"

    check = manager._check({"account": "main"})
    conv = _chat_by_id(check, 123)
    # The chat shows the bot's own reply as the last message ...
    assert conv["last_from"] == {"is_bot": True}
    # ... yet the unread counter is zero: the answered incoming message was
    # marked read and the outgoing reply is not counted.
    assert conv["unread"] == 0
    assert conv["total"] == 2

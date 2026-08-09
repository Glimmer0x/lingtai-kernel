"""Three-boundary Telegram reactions: received / seen / replied.

A human should be able to tell how far an inbound message has travelled:

- \U0001f44c received: the transport/ingress accepted the update.
- \U0001f440 seen: the update was successfully delivered into the agent inbox.
- \u270d\ufe0f replied: a reply targeting that message was sent.

These tests drive ``TelegramManager`` with a fake account that records
reaction calls, so the ordering and the exact emoji are locked.
"""
from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path

from lingtai.mcp_servers.telegram.manager import (
    TelegramManager,
    REACTION_RECEIVED,
    REACTION_SEEN,
    REACTION_REPLIED,
)
from tests._notification_store_helpers import FakeNotificationStore


def _emoji(reaction) -> str:
    if not reaction:
        return None
    first = reaction[0]
    return first.get("emoji") if isinstance(first, dict) else None


class ReactionAccount:
    """Fake account that records every set_message_reaction call."""

    def __init__(self, alias="mybot"):
        self.alias = alias
        self.reactions: list[tuple[str, int, list]] = []
        self._next_id = 100

    def send_message(self, chat_id, text, reply_to_message_id=None, **kwargs):
        msg_id = self._next_id
        self._next_id += 1
        return {"message_id": msg_id}

    def edit_message(self, chat_id, message_id, text, **kwargs):
        return {"ok": True}

    def delete_message(self, chat_id, message_id):
        return {"ok": True}

    def get_task_card(self, chat_id):
        return None

    def set_task_card(self, chat_id, compound_id):
        return None

    def clear_task_card(self, chat_id):
        return None

    def list_task_card_chats(self):
        return []

    def get_last_message_id(self, chat_id):
        return None

    def set_message_reaction(self, chat_id, message_id, reaction):
        self.reactions.append((chat_id, message_id, _emoji(reaction)))


class ReactionService:
    def __init__(self, account):
        self._acct = account
        self.default_account = account

    def get_account(self, alias):
        return self._acct

    def list_accounts(self):
        return [self._acct.alias]

    def taskcard_enabled(self):
        return True

    def taskcard_normal_rows(self):
        return 1


def _manager(tmp_path, acct, delivered=True):
    service = ReactionService(acct)
    manager = TelegramManager(
        service,
        working_dir=Path(tmp_path),
        on_inbound=lambda _: delivered,
        notification_store=FakeNotificationStore(),
    )
    return manager


def _incoming_message():
    return {"message": {
        "message_id": 8,
        "date": 1781600000,
        "from": {"username": "alice"},
        "chat": {"id": 12345, "type": "private"},
        "text": "hello",
    }}


def test_received_then_seen_on_delivered_inbox(tmp_path):
    acct = ReactionAccount()
    manager = _manager(tmp_path, acct, delivered=True)
    manager.on_incoming("mybot", _incoming_message())

    # Ingress first: received (\U0001f44c), then delivered: seen (\U0001f440).
    assert [(chat, mid, em) for (chat, mid, em) in acct.reactions] == [
        (12345, 8, "\U0001f44c"),
        (12345, 8, "\U0001f440"),
    ]


def test_seen_skipped_when_inbox_delivery_fails(tmp_path):
    acct = ReactionAccount()
    manager = _manager(tmp_path, acct, delivered=False)
    manager.on_incoming("mybot", _incoming_message())

    # Only the received boundary fires; no seen reaction for a failed inbox push.
    assert [(chat, mid, em) for (chat, mid, em) in acct.reactions] == [
        (12345, 8, "\U0001f44c"),
    ]


def test_replied_reaction_on_reply_to_original_message(tmp_path):
    acct = ReactionAccount()
    manager = _manager(tmp_path, acct, delivered=True)
    manager.on_incoming("mybot", _incoming_message())
    acct.reactions.clear()

    manager._send({
        "chat_id": 12345,
        "_reply_to_message_id": 8,
        "text": "hi back",
    })

    # The reply targets the original Telegram message: replied (\u270d\ufe0f).
    assert [(chat, mid, em) for (chat, mid, em) in acct.reactions] == [
        (12345, 8, "\u270d\ufe0f"),
    ]


def test_deprecated_done_alias_points_to_replied():
    from lingtai.mcp_servers.telegram.manager import REACTION_DONE
    assert REACTION_DONE is REACTION_REPLIED

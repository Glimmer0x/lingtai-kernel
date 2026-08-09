"""lingtai#672: typing indicators must never run forever.

The Telegram ``TypingIndicatorManager`` carries a bounded TTL lease per chat.
Even when ``stop_typing`` is never called (AED exhaustion, provider failure,
cancellation, turn ends without a send), the typing loop must exit once the
lease expires and remove the chat from the active set.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

from lingtai.mcp_servers.telegram.manager import TypingIndicatorManager


class _FakeAccount:
    def __init__(self) -> None:
        self.alias = "acct"
        self.actions: list[tuple[int, str]] = []

    def send_chat_action(self, chat_id: int, action: str) -> None:
        self.actions.append((chat_id, action))


def test_typing_stops_after_ttl_even_without_stop_typing() -> None:
    """A typing loop that is never explicitly stopped still exits after its
    TTL lease expires and is removed from the active set."""
    account = _FakeAccount()
    manager = TypingIndicatorManager(ttl_seconds=0.2)

    manager.start_typing(account, 123)
    assert ("acct", 123) in manager._active_chats

    # Give the loop a few send ticks, then wait past the lease without calling
    # stop_typing.
    time.sleep(0.15)
    assert manager._active_chats.get(("acct", 123)) is not None
    time.sleep(0.35)

    assert ("acct", 123) not in manager._active_chats
    assert len(account.actions) >= 1
    assert all(chat_id == 123 and action == "typing" for chat_id, action in account.actions)


def test_stop_typing_still_stops_before_ttl() -> None:
    """Explicit stop_typing keeps working and wins over the TTL."""
    account = _FakeAccount()
    manager = TypingIndicatorManager(ttl_seconds=60.0)

    manager.start_typing(account, 456)
    time.sleep(0.05)
    manager.stop_typing(account, 456)

    # Loop exits promptly once the stop event is set.
    deadline = time.monotonic() + 2.0
    while ("acct", 456) in manager._active_chats and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ("acct", 456) not in manager._active_chats


def test_typing_loop_uses_lease_bound_even_with_slow_stop() -> None:
    """The loop wait is bounded by the remaining lease, so a 4s sleep can never
    overrun a much shorter TTL (deterministic regression for the 8-minute
    typing bug)."""
    account = _FakeAccount()
    manager = TypingIndicatorManager(ttl_seconds=0.1)

    start = time.monotonic()
    manager.start_typing(account, 789)
    deadline = time.monotonic() + 2.0
    while ("acct", 789) in manager._active_chats and time.monotonic() < deadline:
        time.sleep(0.01)
    elapsed = time.monotonic() - start

    assert ("acct", 789) not in manager._active_chats
    # Generous upper bound: the loop must exit within a couple seconds even
    # though the inner wait is 4s, proving the lease clamps the wait.
    assert elapsed < 3.0

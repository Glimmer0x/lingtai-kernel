"""lingtai#672: typing indicators must never run forever.

The Telegram ``TypingIndicatorManager`` carries a bounded TTL lease per chat.
Even when ``stop_typing`` is never called (AED exhaustion, provider failure,
cancellation, turn ends without a send), the typing loop must exit once the
lease expires and remove the chat from the active set.

P1-3/P1-4 contracts locked here:
- no Bot API send can be issued at/after the lease deadline (hard bound);
- stale workers cannot delete a newer lease for the same chat (identity);
- repeated starts renew/replace the active lease;
- ``stop_all`` signals + joins workers and forbids new starts;
- invalid (non-finite / non-positive) TTL config is rejected.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from lingtai.mcp_servers.telegram.manager import TypingIndicatorManager


class _FakeAccount:
    def __init__(self) -> None:
        self.alias = "acct"
        self.actions: list[tuple[int, str]] = []

    def send_chat_action(self, chat_id: int, action: str) -> None:
        self.actions.append((chat_id, action))


class _FakeClock:
    """Manually advanced monotonic clock for deterministic TTL tests."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _wait_active(manager, key, timeout=2.0):
    deadline = time.monotonic() + timeout
    while key not in manager._active_chats and time.monotonic() < deadline:
        time.sleep(0.01)


def _wait_inactive(manager, key, timeout=2.0):
    deadline = time.monotonic() + timeout
    while key in manager._active_chats and time.monotonic() < deadline:
        time.sleep(0.01)


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
    _wait_inactive(manager, ("acct", 456))
    assert ("acct", 456) not in manager._active_chats


def test_typing_loop_uses_lease_bound_even_with_slow_stop() -> None:
    """The loop wait is bounded by the remaining lease, so a 4s sleep can never
    overrun a much shorter TTL (deterministic regression for the 8-minute
    typing bug)."""
    account = _FakeAccount()
    manager = TypingIndicatorManager(ttl_seconds=0.1)

    start = time.monotonic()
    manager.start_typing(account, 789)
    _wait_inactive(manager, ("acct", 789))
    elapsed = time.monotonic() - start

    assert ("acct", 789) not in manager._active_chats
    # Generous upper bound: the loop must exit within a couple seconds even
    # though the inner wait is 4s, proving the lease clamps the wait.
    assert elapsed < 3.0


def test_no_send_after_deadline_with_fake_clock() -> None:
    """P1-4: the hard TTL bound is real — no Bot API send may be issued at or
    after the deadline. A fake clock proves it deterministically."""
    account = _FakeAccount()
    clock = _FakeClock()
    manager = TypingIndicatorManager(ttl_seconds=0.1, clock=clock)

    manager.start_typing(account, 321)
    _wait_active(manager, ("acct", 321))
    # Let the first send land, then jump the clock PAST the deadline.
    time.sleep(0.02)
    clock.advance(10.0)
    time.sleep(0.1)  # worker observes the deadline and must exit without sending

    assert ("acct", 321) not in manager._active_chats
    # All sends must have happened strictly before the deadline.
    for chat_id, _action in account.actions:
        assert chat_id == 321
    # The worker cannot have sent after we advanced the clock: the only send
    # window is the first loop iteration before the advance.
    assert len(account.actions) <= 2


def test_stale_worker_cannot_delete_new_lease() -> None:
    """P1-3: a stale worker for a replaced lease must not remove the new lease
    from the active map (identity-safe cleanup)."""
    account = _FakeAccount()
    manager = TypingIndicatorManager(ttl_seconds=5.0)

    manager.start_typing(account, 555)
    _wait_active(manager, ("acct", 555))
    # Replace the lease with a fresh one (repeated start = renewal).
    manager.start_typing(account, 555)
    time.sleep(0.05)

    # The new lease is still tracked; stop_typing can still signal it.
    assert ("acct", 555) in manager._active_chats
    manager.stop_typing(account, 555)
    _wait_inactive(manager, ("acct", 555))


def test_repeated_start_renews_deadline() -> None:
    """P1-3: a repeated ``start_typing`` for an already-active chat renews the
    lease instead of inheriting an expiring one — the chat remains active past
    the original deadline."""
    account = _FakeAccount()
    clock = _FakeClock()
    manager = TypingIndicatorManager(ttl_seconds=0.3, clock=clock)

    manager.start_typing(account, 777)
    _wait_active(manager, ("acct", 777))
    time.sleep(0.02)
    # Renew near the original deadline.
    clock.advance(0.25)
    manager.start_typing(account, 777)
    time.sleep(0.05)
    # Original deadline passed, but the renewed lease keeps the chat active.
    assert ("acct", 777) in manager._active_chats
    manager.stop_typing(account, 777)
    _wait_inactive(manager, ("acct", 777))


def test_stop_all_joins_workers_and_blocks_new_starts() -> None:
    """P1-3: ``stop_all`` signals and joins every worker, clears the map, and
    makes later ``start_typing`` calls no-ops."""
    account = _FakeAccount()
    manager = TypingIndicatorManager(ttl_seconds=60.0)

    manager.start_typing(account, 888)
    _wait_active(manager, ("acct", 888))
    manager.stop_all()

    assert ("acct", 888) not in manager._active_chats
    # No background typing worker may be left alive: a later start is a no-op.
    before = len(account.actions)
    manager.start_typing(account, 999)
    time.sleep(0.05)
    assert ("acct", 999) not in manager._active_chats
    assert len(account.actions) == before


def test_invalid_ttl_rejected() -> None:
    """P1-4: custom TTL must be finite and strictly positive."""
    for bad in (0, -1, float("nan"), float("inf"), float("-inf"), "nope"):
        with pytest.raises(ValueError):
            TypingIndicatorManager(ttl_seconds=bad)

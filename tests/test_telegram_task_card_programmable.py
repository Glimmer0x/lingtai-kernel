"""Tests for Telegram's read-only projection of the intrinsic Task Card files."""

from __future__ import annotations

from pathlib import Path

from lingtai.mcp_servers.telegram.manager import TelegramManager
from tests._notification_store_helpers import notification_store_for


class FakeAccount:
    alias = "mybot"

    def __init__(self):
        self.calls: list = []
        self.sent: dict[int, str] = {}
        self._resident: dict[int, str] = {}

    def send_message(self, chat_id, text, reply_to_message_id=None, **kwargs):
        msg_id = len(self.calls) + 100
        self.sent[msg_id] = text
        self.calls.append(("send", chat_id, text))
        return {"message_id": msg_id}

    def edit_message(self, chat_id, message_id, text, **kwargs):
        self.sent[message_id] = text
        self.calls.append(("edit", chat_id, message_id, text))
        return {"ok": True}

    def delete_message(self, chat_id, message_id, **kwargs):
        self.calls.append(("delete", chat_id, message_id))
        return {"ok": True}

    def get_task_card(self, chat_id):
        return self._resident.get(chat_id)

    def set_task_card(self, chat_id, compound_id):
        self._resident[chat_id] = compound_id

    def list_task_card_chats(self):
        return sorted(self._resident)


class FakeService:
    def __init__(self):
        self.default_account = FakeAccount()
        self._enabled = True

    def get_account(self, alias):
        assert alias == "mybot"
        return self.default_account

    def list_accounts(self):
        return ["mybot"]

    def taskcard_enabled(self):
        return self._enabled

    def set_taskcard_enabled(self, enabled):
        self._enabled = enabled

    def taskcard_normal_rows(self):
        return 1


def _manager(tmp_path):
    service = FakeService()
    manager = TelegramManager(
        service,
        working_dir=Path(tmp_path),
        on_inbound=lambda _: None,
        notification_store=notification_store_for(Path(tmp_path)),
    )
    return manager, service.default_account, service


def _auto(manager, reasoning="build"):
    return manager._handle_task_card_update(
        {
            "sub_action": "create",
            "account": "mybot",
            "chat_id": 55,
            "tool": "bash",
            "tool_action": "run",
            "reasoning": reasoning,
        }
    )


def _write_intrinsic_taskcard(tmp_path: Path, *, status: str, body: str | None) -> None:
    taskcard_dir = tmp_path / "taskcard"
    taskcard_dir.mkdir(parents=True, exist_ok=True)
    (taskcard_dir / "status").write_text(status, encoding="utf-8")
    body_path = taskcard_dir / "taskcard.md"
    if body is None:
        if body_path.exists():
            body_path.unlink()
    else:
        body_path.write_text(body, encoding="utf-8")


def _current(account: FakeAccount) -> str:
    return account.sent[max(account.sent)]


def test_active_intrinsic_body_projects_onto_existing_resident(tmp_path):
    manager, acct, _service = _manager(tmp_path)
    _auto(manager, reasoning="compiling")
    _write_intrinsic_taskcard(tmp_path, status="active", body="# Task Card\n\n- first\n")

    manager._broadcast_programmable_task_card_file()

    text = _current(acct)
    assert "compiling" in text
    assert "— WATCH —" in text
    assert "# Task Card" in text
    assert "- first" in text


def test_projection_is_diff_only_against_last_programmable_frame(tmp_path):
    manager, acct, _service = _manager(tmp_path)
    _auto(manager)
    _write_intrinsic_taskcard(tmp_path, status="active", body="same body\n")

    manager._broadcast_programmable_task_card_file()
    calls_after_first = len(acct.calls)
    manager._broadcast_programmable_task_card_file()

    assert len(acct.calls) == calls_after_first
    assert manager._task_card_channels["mybot:55"]["programmable"] == "same body\n"


def test_inactive_or_invalid_state_is_noop_and_preserves_last_good_projection(tmp_path):
    manager, acct, _service = _manager(tmp_path)
    _auto(manager)
    _write_intrinsic_taskcard(tmp_path, status="active", body="v1\n")
    manager._broadcast_programmable_task_card_file()
    calls_after_good = len(acct.calls)

    _write_intrinsic_taskcard(tmp_path, status="inactive", body="v2\n")
    manager._broadcast_programmable_task_card_file()
    assert len(acct.calls) == calls_after_good
    assert manager._task_card_channels["mybot:55"]["programmable"] == "v1\n"

    _write_intrinsic_taskcard(tmp_path, status="active", body="   ")
    manager._broadcast_programmable_task_card_file()
    assert len(acct.calls) == calls_after_good
    assert manager._task_card_channels["mybot:55"]["programmable"] == "v1\n"


def test_missing_body_after_active_status_is_noop_and_keeps_last_good_projection(tmp_path):
    manager, acct, _service = _manager(tmp_path)
    _auto(manager)
    _write_intrinsic_taskcard(tmp_path, status="active", body="v1\n")
    manager._broadcast_programmable_task_card_file()
    calls_after_good = len(acct.calls)

    _write_intrinsic_taskcard(tmp_path, status="active", body=None)
    manager._broadcast_programmable_task_card_file()

    assert len(acct.calls) == calls_after_good
    assert manager._task_card_channels["mybot:55"]["programmable"] == "v1\n"


def test_existing_automatic_channel_behavior_is_preserved_by_programmable_file_updates(tmp_path):
    manager, acct, _service = _manager(tmp_path)
    _auto(manager, reasoning="stay put")
    automatic_only = _current(acct)
    _write_intrinsic_taskcard(tmp_path, status="active", body="watch body\n")

    manager._broadcast_programmable_task_card_file()
    assert "stay put" in _current(acct)
    assert "watch body" in _current(acct)

    manager._handle_task_card_update(
        {
            "sub_action": "update",
            "card_message_id": "mybot:55:100",
            "tool": "read",
            "tool_action": "open",
            "reasoning": "next step",
        }
    )
    assert "next step" in _current(acct)
    assert "watch body" in _current(acct)
    assert automatic_only != _current(acct)


def test_inactive_stops_rendering_without_deleting_or_hiding_existing_resident(tmp_path):
    """`stop`/`remove`-style inactive must gate the render loop only.

    The existing Telegram message and its tracked slot must survive untouched,
    even once the local body file itself is later deleted (as `task_card.remove`
    does) while status stays `inactive`.
    """
    manager, acct, _service = _manager(tmp_path)
    _auto(manager)
    _write_intrinsic_taskcard(tmp_path, status="active", body="v1\n")
    manager._broadcast_programmable_task_card_file()

    resident_before = acct.get_task_card(55)
    calls_before = list(acct.calls)
    assert resident_before is not None
    assert "v1" in _current(acct)

    # `stop` writes inactive but leaves the last body on disk (possibly stale).
    _write_intrinsic_taskcard(tmp_path, status="inactive", body="v2 (must not render)\n")
    manager._broadcast_programmable_task_card_file()
    manager._broadcast_programmable_task_card_file()

    assert acct.calls == calls_before
    assert not any(call[0] == "delete" for call in acct.calls)
    assert acct.get_task_card(55) == resident_before
    assert 55 in acct.list_task_card_chats()
    assert "v1" in _current(acct)
    assert manager._task_card_channels["mybot:55"]["programmable"] == "v1\n"

    # `remove` additionally deletes the local body once inactive is durable;
    # Telegram must remain a pure no-op rather than deleting/hiding anything.
    (tmp_path / "taskcard" / "taskcard.md").unlink()
    manager._broadcast_programmable_task_card_file()

    assert acct.calls == calls_before
    assert not any(call[0] == "delete" for call in acct.calls)
    assert acct.get_task_card(55) == resident_before
    assert "v1" in _current(acct)


def test_new_active_watch_after_inactive_renders_without_stale_state_corruption(tmp_path):
    """A fresh watch after `stop`/`remove` must render cleanly, not resurface old content."""
    manager, acct, _service = _manager(tmp_path)
    _auto(manager)
    _write_intrinsic_taskcard(tmp_path, status="active", body="v1\n")
    manager._broadcast_programmable_task_card_file()
    resident_id = acct.get_task_card(55)
    assert "v1" in _current(acct)

    # Old watch retires and its body is removed, exactly as `task_card.remove` does.
    _write_intrinsic_taskcard(tmp_path, status="inactive", body=None)
    manager._broadcast_programmable_task_card_file()
    assert manager._task_card_channels["mybot:55"]["programmable"] == "v1\n"

    # A brand-new watch starts: body written first, then status flips to active.
    _write_intrinsic_taskcard(tmp_path, status="active", body="v2 fresh\n")
    manager._broadcast_programmable_task_card_file()

    text = _current(acct)
    assert "v2 fresh" in text
    assert "v1" not in text
    assert manager._task_card_channels["mybot:55"]["programmable"] == "v2 fresh\n"
    assert acct.get_task_card(55) == resident_id
    assert acct.calls[-1][0] == "edit"

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

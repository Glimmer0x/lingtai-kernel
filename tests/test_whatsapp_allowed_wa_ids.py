"""Regression tests for WhatsApp's canonical inbound sender filter (issue #727)."""
from __future__ import annotations

from pathlib import Path

import pytest

from lingtai.mcp_servers.whatsapp import manager as whatsapp_manager_module
from lingtai.mcp_servers.whatsapp.manager import WhatsAppManager


SENDER = "15551234567@c.us"


def _manager(tmp_path: Path, **config: object) -> WhatsAppManager:
    values: dict[str, object] = {
        "store_dir": str(tmp_path / "store"),
        "autostart": False,
    }
    values.update(config)
    return WhatsAppManager(values, working_dir=tmp_path)


def _message(message_id: str, sender: str = SENDER) -> dict[str, object]:
    return {
        "id": message_id,
        "from": sender,
        "body": "hello",
        "type": "chat",
        "timestamp": 1_700_000_000,
    }


def _inbox_files(manager: WhatsAppManager) -> list[Path]:
    return sorted(manager.store_dir.rglob("inbox/*.json"))


@pytest.fixture()
def pushes(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, object]]:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        whatsapp_manager_module,
        "push_inbox_event",
        lambda **kwargs: captured.append(kwargs),
    )
    return captured


def test_allowed_wa_ids_drops_before_storage_and_notification(
    tmp_path: Path, pushes: list[dict[str, object]]
) -> None:
    manager = _manager(tmp_path, allowed_wa_ids=["19998887777"])

    manager._handle_incoming(_message("wamid.denied"))

    assert _inbox_files(manager) == []
    assert pushes == []


def test_allowed_wa_ids_allows_listed_sender(tmp_path: Path, pushes: list[dict[str, object]]) -> None:
    manager = _manager(tmp_path, allowed_wa_ids=["15551234567"])

    manager._handle_incoming(_message("wamid.allowed"))

    assert len(_inbox_files(manager)) == 1
    assert len(pushes) == 1
    assert pushes[0]["metadata"]["from"] == SENDER  # type: ignore[index]


def test_allowed_wa_ids_normalizes_formatted_and_integer_entries(
    tmp_path: Path, pushes: list[dict[str, object]]
) -> None:
    manager = _manager(tmp_path, allowed_wa_ids=["+1 (555) 123-4567", 15551234567])

    manager._handle_incoming(_message("wamid.formatted"))

    assert len(_inbox_files(manager)) == 1
    assert len(pushes) == 1


def test_absent_or_empty_allowed_wa_ids_preserves_allow_all_behavior(
    tmp_path: Path, pushes: list[dict[str, object]]
) -> None:
    absent = _manager(tmp_path / "absent")
    empty = _manager(tmp_path / "empty", allowed_wa_ids=[])

    absent._handle_incoming(_message("wamid.absent", sender="19998887777@c.us"))
    empty._handle_incoming(_message("wamid.empty", sender="19998887777@c.us"))

    assert len(_inbox_files(absent)) == 1
    assert len(_inbox_files(empty)) == 1
    assert len(pushes) == 2


def test_allowed_users_remains_a_legacy_alias(tmp_path: Path, pushes: list[dict[str, object]]) -> None:
    manager = _manager(tmp_path, allowed_users=["15551234567"])

    manager._handle_incoming(_message("wamid.legacy"))
    manager._handle_incoming(_message("wamid.blocked", sender="19998887777@c.us"))

    assert len(_inbox_files(manager)) == 1
    assert len(pushes) == 1


def test_explicit_allowed_wa_ids_takes_precedence_over_legacy_alias(tmp_path: Path) -> None:
    manager = _manager(
        tmp_path,
        allowed_wa_ids=[],
        allowed_users=["15551234567"],
    )

    assert manager.allowed_wa_ids is None
    assert manager.allowed_users is None


def test_account_details_and_status_expose_only_filter_count(tmp_path: Path) -> None:
    manager = _manager(tmp_path, allowed_wa_ids=["15551234567", "19998887777"])

    details = manager.account_details()[0]
    status = manager._status({})

    assert details["allowed_wa_ids_count"] == 2
    assert status["allowed_wa_ids_count"] == 2
    assert "15551234567" not in repr(details)
    assert "19998887777" not in repr(status)


def test_unfiltered_account_omits_filter_count(tmp_path: Path) -> None:
    manager = _manager(tmp_path)

    assert "allowed_wa_ids_count" not in manager.account_details()[0]
    assert "allowed_wa_ids_count" not in manager._status({})

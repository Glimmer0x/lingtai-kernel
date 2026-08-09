"""Regression tests for inbound WhatsApp webhook replay suppression.

Meta's Cloud API webhook delivery is at-least-once: whenever the receiver does
not answer with a timely HTTP 200, Meta re-delivers the same notification with
the same stable messages[].id (wamid) with backoff for hours. Before the replay
guard, every redelivery landed a duplicate inbox entry under a fresh local UUID
and woke the agent again. These tests pin the idempotency guard (mirroring the
WeChat manager's inbox_seen.json design) that suppresses such replays while
preserving genuinely new messages.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingtai.mcp_servers.whatsapp.manager import WhatsAppManager

ACCESS_TOKEN = "secret-access-token"
APP_SECRET = "secret-app-secret"


def _manager(tmp_path: Path, *, on_inbound=None) -> WhatsAppManager:
    return WhatsAppManager(
        accounts_config=[
            {
                "alias": "default",
                "phone_number_id": "10001",
                "access_token": ACCESS_TOKEN,
                "app_secret": APP_SECRET,
            }
        ],
        working_dir=tmp_path,
        on_inbound=on_inbound,
    )


def _webhook_payload(*messages: dict) -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": "10001"},
                            "messages": list(messages),
                        }
                    }
                ]
            }
        ]
    }


def _text_message(wamid: str, body: str, *, wa_id: str = "15551234567") -> dict:
    return {
        "from": wa_id,
        "id": wamid,
        "timestamp": "1752000000",
        "type": "text",
        "text": {"body": body},
    }


def _inbox_entries(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "whatsapp" / "default" / "inbox").glob("*/message.json"))


def test_duplicate_webhook_delivery_lands_once(tmp_path):
    inbound: list[dict] = []
    manager = _manager(tmp_path, on_inbound=inbound.append)
    payload = _webhook_payload(_text_message("wamid.A", "hello"))

    first = manager.ingest_webhook("default", payload)
    second = manager.ingest_webhook("default", payload)

    # One inbox landing, one wake; the return value is unchanged by the guard.
    assert len(_inbox_entries(tmp_path)) == 1
    assert len(inbound) == 1
    assert first == second


def test_distinct_wamids_both_land(tmp_path):
    inbound: list[dict] = []
    manager = _manager(tmp_path, on_inbound=inbound.append)

    manager.ingest_webhook("default", _webhook_payload(_text_message("wamid.A", "hello")))
    manager.ingest_webhook("default", _webhook_payload(_text_message("wamid.B", "hello")))

    assert len(_inbox_entries(tmp_path)) == 2
    assert len(inbound) == 2


def test_same_text_different_message_ids_not_deduped(tmp_path):
    manager = _manager(tmp_path)

    manager.ingest_webhook("default", _webhook_payload(_text_message("wamid.A", "same text")))
    manager.ingest_webhook("default", _webhook_payload(_text_message("wamid.B", "same text")))

    # Identical content but distinct wamids are different messages: both land.
    assert len(_inbox_entries(tmp_path)) == 2


def test_seen_state_survives_restart(tmp_path):
    inbound: list[dict] = []
    manager = _manager(tmp_path, on_inbound=inbound.append)
    payload = _webhook_payload(_text_message("wamid.A", "hello"))
    manager.ingest_webhook("default", payload)
    assert len(inbound) == 1

    # New manager over the same working_dir reloads inbox_seen.json.
    restarted = _manager(tmp_path, on_inbound=inbound.append)
    restarted.ingest_webhook("default", payload)

    assert len(_inbox_entries(tmp_path)) == 1
    assert len(inbound) == 1


def test_corrupt_seen_file_degrades_gracefully(tmp_path):
    seen = tmp_path / "whatsapp" / "inbox_seen.json"
    seen.parent.mkdir(parents=True, exist_ok=True)
    seen.write_text("{not json", encoding="utf-8")

    manager = _manager(tmp_path)
    manager.ingest_webhook("default", _webhook_payload(_text_message("wamid.A", "hello")))

    # Corrupt guard state must not crash boot and ingest still works.
    assert len(_inbox_entries(tmp_path)) == 1


def test_missing_message_id_never_suppressed(tmp_path):
    manager = _manager(tmp_path)
    payload = _webhook_payload(
        {
            "from": "15551234567",
            "timestamp": "1752000000",
            "type": "text",
            "text": {"body": "no id"},
        }
    )

    manager.ingest_webhook("default", payload)
    manager.ingest_webhook("default", payload)

    # No stable upstream id -> no dedup key: both deliveries land.
    assert len(_inbox_entries(tmp_path)) == 2


def test_seen_keys_fifo_eviction(tmp_path, monkeypatch):
    from lingtai.mcp_servers.whatsapp import manager as whatsapp_manager_module

    monkeypatch.setattr(whatsapp_manager_module, "SEEN_KEYS_MAX", 3)
    manager = _manager(tmp_path)
    payloads = [_webhook_payload(_text_message(f"wamid.{i}", f"msg {i}")) for i in range(4)]
    for payload in payloads:
        manager.ingest_webhook("default", payload)
    assert len(_inbox_entries(tmp_path)) == 4

    # Oldest key was evicted: replaying wamid.0 lands again.
    manager.ingest_webhook("default", payloads[0])
    # Newest key is still in the window: replaying wamid.3 is suppressed.
    manager.ingest_webhook("default", payloads[3])

    assert len(_inbox_entries(tmp_path)) == 5


def test_record_after_store_ordering(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    real_store = WhatsAppManager._store_message
    calls = {"n": 0}

    def flaky_store(self, alias, folder, msg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real_store(self, alias, folder, msg)

    monkeypatch.setattr(WhatsAppManager, "_store_message", flaky_store)
    payload = _webhook_payload(_text_message("wamid.A", "hello"))

    with pytest.raises(OSError):
        manager.ingest_webhook("default", payload)
    # The key must NOT have been recorded for the failed write: retrying the
    # same payload lands the message instead of suppressing it.
    manager.ingest_webhook("default", payload)

    assert len(_inbox_entries(tmp_path)) == 1


def test_stored_message_keeps_stable_key_provenance(tmp_path):
    manager = _manager(tmp_path)
    manager.ingest_webhook("default", _webhook_payload(_text_message("wamid.A", "hello")))

    stored = json.loads(_inbox_entries(tmp_path)[0].read_text(encoding="utf-8"))
    assert stored["stable_key"] == "default|15551234567|mid:wamid.A"

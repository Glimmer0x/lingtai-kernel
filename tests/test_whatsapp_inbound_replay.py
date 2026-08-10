"""Regression tests for inbound WhatsApp replay suppression (bridge mode).

whatsapp-web.js redelivery is at-least-once: on reconnect, process restart, or
an interrupted stream the bridge re-emits the same message with the same
stable wamid (``msg.id._serialized``, normalized into ``msg["id"]`` by the
bridge). Before the replay guard every redelivery woke the agent again. These
tests pin the idempotency guard (mirroring the WeChat manager's
inbox_seen.json design) that suppresses such replays while preserving
genuinely new messages.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from lingtai.mcp_servers.whatsapp import manager as whatsapp_manager_module
from lingtai.mcp_servers.whatsapp.manager import WhatsAppManager

SENDER = "15551234567@c.us"


def _manager(tmp_path: Path) -> WhatsAppManager:
    # autostart=False keeps the test hermetic: no Node bridge subprocess.
    return WhatsAppManager(
        {"store_dir": str(tmp_path / "store"), "autostart": False},
        working_dir=tmp_path,
    )


def _message(wamid: str, body: str) -> dict:
    """Bridge-normalized message shape (see bridge/index.js normalizeMessage)."""
    return {
        "id": wamid,
        "from": SENDER,
        "body": body,
        # whatsapp-web.js emits 'chat' for plain text, never 'text'.
        "type": "chat",
        "timestamp": 1752000000,
    }


def _inbox_entries(tmp_path: Path) -> list[Path]:
    # store_dir/<sanitized JID>/inbox/*.json; "15551234567@c.us" sanitizes to
    # "15551234567_c.us" (only [A-Za-z0-9_.-] survives _safe_component).
    return sorted((tmp_path / "store" / "15551234567_c.us" / "inbox").glob("*.json"))


def _collect_pushes(monkeypatch) -> list[dict]:
    pushes: list[dict] = []
    monkeypatch.setattr(
        whatsapp_manager_module, "push_inbox_event",
        lambda **kw: pushes.append(kw),
    )
    return pushes


def test_duplicate_delivery_lands_once(tmp_path, monkeypatch):
    pushes = _collect_pushes(monkeypatch)
    manager = _manager(tmp_path)
    msg = _message("wamid.A", "hello")

    manager._handle_incoming(msg)
    manager._handle_incoming(msg)

    # One inbox landing, one wake; the second delivery is suppressed.
    assert len(_inbox_entries(tmp_path)) == 1
    assert len(pushes) == 1


def test_distinct_wamids_both_land(tmp_path, monkeypatch):
    pushes = _collect_pushes(monkeypatch)
    manager = _manager(tmp_path)

    manager._handle_incoming(_message("wamid.A", "hello"))
    manager._handle_incoming(_message("wamid.B", "hello"))

    assert len(_inbox_entries(tmp_path)) == 2
    assert len(pushes) == 2


def test_same_text_different_message_ids_not_deduped(tmp_path):
    manager = _manager(tmp_path)

    manager._handle_incoming(_message("wamid.A", "same text"))
    manager._handle_incoming(_message("wamid.B", "same text"))

    # Identical content but distinct wamids are different messages: both land.
    assert len(_inbox_entries(tmp_path)) == 2


def test_seen_state_survives_restart(tmp_path, monkeypatch):
    pushes = _collect_pushes(monkeypatch)
    manager = _manager(tmp_path)
    msg = _message("wamid.A", "hello")
    manager._handle_incoming(msg)
    assert len(pushes) == 1

    # New manager over the same working_dir reloads inbox_seen.json.
    restarted = _manager(tmp_path)
    restarted._handle_incoming(msg)

    assert len(_inbox_entries(tmp_path)) == 1
    assert len(pushes) == 1


def test_corrupt_seen_file_degrades_gracefully(tmp_path):
    seen = tmp_path / "store" / "inbox_seen.json"
    seen.parent.mkdir(parents=True, exist_ok=True)
    seen.write_text("{not json", encoding="utf-8")

    manager = _manager(tmp_path)
    manager._handle_incoming(_message("wamid.A", "hello"))

    # Corrupt guard state must not crash boot and ingest still works.
    assert len(_inbox_entries(tmp_path)) == 1


def test_missing_message_id_never_suppressed(tmp_path, monkeypatch):
    pushes = _collect_pushes(monkeypatch)
    manager = _manager(tmp_path)
    msg = {
        "from": SENDER,
        "body": "no id",
        "type": "chat",
        "timestamp": 1752000000,
    }

    manager._handle_incoming(msg)
    manager._handle_incoming(msg)

    # No stable upstream id -> no dedup key: both deliveries land.
    assert len(_inbox_entries(tmp_path)) == 2
    assert len(pushes) == 2


def test_seen_keys_fifo_eviction(tmp_path, monkeypatch):
    pushes = _collect_pushes(monkeypatch)
    monkeypatch.setattr(whatsapp_manager_module, "SEEN_KEYS_MAX", 3)
    manager = _manager(tmp_path)
    msgs = [_message(f"wamid.{i}", f"msg {i}") for i in range(4)]
    for msg in msgs:
        manager._handle_incoming(msg)
    assert len(_inbox_entries(tmp_path)) == 4

    # Oldest key was evicted: replaying wamid.0 wakes the agent again.
    manager._handle_incoming(msgs[0])
    # Newest key is still in the window: replaying wamid.3 is suppressed.
    manager._handle_incoming(msgs[3])

    # 4 initial landings + 1 re-landing of the evicted wamid.0; wamid.3 replay
    # suppressed. The re-landed file overwrites wamid.0.json, so file count
    # stays at 4 while the wake count reflects the re-processing.
    assert len(pushes) == 5
    assert len(_inbox_entries(tmp_path)) == 4


def test_record_after_store_ordering(tmp_path, monkeypatch):
    manager = _manager(tmp_path)
    real_store = WhatsAppManager._store_message
    calls = {"n": 0}

    def flaky_store(self, wa_id, direction, msg):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real_store(self, wa_id, direction, msg)

    monkeypatch.setattr(WhatsAppManager, "_store_message", flaky_store)
    msg = _message("wamid.A", "hello")

    with pytest.raises(OSError):
        manager._handle_incoming(msg)
    # The key must NOT have been recorded for the failed write: retrying the
    # same message lands it instead of suppressing it.
    manager._handle_incoming(msg)

    assert len(_inbox_entries(tmp_path)) == 1


def test_stored_message_keeps_stable_key_provenance(tmp_path):
    manager = _manager(tmp_path)
    manager._handle_incoming(_message("wamid.A", "hello"))

    stored = json.loads(_inbox_entries(tmp_path)[0].read_text(encoding="utf-8"))
    assert stored["stable_key"] == f"{SENDER}|mid:wamid.A"

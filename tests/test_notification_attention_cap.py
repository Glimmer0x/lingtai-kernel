"""Tests for the 10k character cap on the attention notification lane.

The attention lane (``_meta.agent_meta.notifications.attention``) is re-stamped
on every eligible tool batch and on every IDLE/ASLEEP synthesized pair, so a
busy hub agent (many unread emails plus several IM lanes) could grow context
fast and pay a large per-call cache miss.  The cap shares the
``LINGTAI_NOTIFICATION_MAX_CHARS`` env bar with the persistent lane (single
upper limit across all notification channels, Jason 2026-08-13); over the cap
it spills the full attention lane to ``logs/notification-attention-overflow-<ts>.json``
and returns a compacted copy with an ``overflow`` marker that points the agent
at the file (or the producer tool when the spill failed).
"""
from __future__ import annotations

import copy
import json
import os
from types import SimpleNamespace

import lingtai.kernel.meta_block as meta_block

MAX = meta_block.NOTIFICATION_ATTENTION_MAX_CHARS
ENV = meta_block.NOTIFICATION_ATTENTION_MAX_CHARS_ENV


def _cap_agent(tmp_path):
    return SimpleNamespace(_working_dir=str(tmp_path))


def _attention_chars(attention: dict) -> int:
    return len(json.dumps(attention, ensure_ascii=False, sort_keys=True))


def _spill_files(tmp_path):
    return sorted(
        (tmp_path / "logs").glob("notification-attention-overflow-*.json")
    )


def _telegram_message(message_id: int, *, text: str) -> dict:
    return {
        "id": f"main:123:{message_id}",
        "direction": "incoming",
        "sender": "Jason",
        "text": text,
        "text_truncated": False,
    }


def _attention_payload(messages: list[dict]) -> dict:
    # Raw attention lane shape: producer source -> payload (as built by
    # ``build_notification_payload``).
    return {
        "mcp.telegram": {
            "data": {
                "count": len(messages),
                "previews": [
                    {
                        "from": "Jason",
                        "subject": "telegram message from Jason via main",
                        "message_ref": messages[-1]["id"],
                        "recent_messages": messages,
                    }
                ],
            }
        }
    }


def test_small_attention_unchanged_and_no_spill(tmp_path):
    agent = _cap_agent(tmp_path)
    messages = [_telegram_message(i, text=f"message {i}") for i in range(1, 4)]
    attention = _attention_payload(messages)

    capped = meta_block._cap_notification_attention(agent, attention)

    assert "overflow" not in capped
    assert capped == attention
    assert _attention_chars(capped) <= MAX
    assert not (tmp_path / "logs").exists() or _spill_files(tmp_path) == []


def test_large_attention_spills_and_compacts(tmp_path):
    agent = _cap_agent(tmp_path)
    messages = [_telegram_message(i, text="T" * 3000) for i in range(1, 41)]
    attention = _attention_payload(messages)
    original = copy.deepcopy(attention)

    capped = meta_block._cap_notification_attention(agent, attention)

    assert _attention_chars(capped) <= MAX
    overflow = capped["overflow"]
    assert overflow["truncated"] is True
    assert overflow["full_chars"] > MAX
    spill_files = _spill_files(tmp_path)
    assert len(spill_files) == 1
    assert overflow["path"] == str(spill_files[0])

    # The spill file holds the FULL original attention lane, not the compacted one.
    spilled = json.loads(spill_files[0].read_text(encoding="utf-8"))
    spilled_messages = spilled["mcp.telegram"]["data"]["previews"][0]["recent_messages"]
    assert spilled_messages[0]["text"] == "T" * 3000

    # Structural/routing fields survive; heavy text is capped with the marker.
    preview = capped["mcp.telegram"]["data"]["previews"][0]
    assert preview["from"] == "Jason"
    assert preview["message_ref"] == "main:123:40"
    for message in preview["recent_messages"]:
        assert len(message["text"]) < 3000
        assert message["direction"] == "incoming"
        assert message["sender"] == "Jason"
    assert spill_files[0].name in capped["comment"]

    # The caller's attention dict is never mutated.
    assert attention == original


def test_attention_overflow_comment_points_at_the_spill_file(tmp_path):
    agent = _cap_agent(tmp_path)
    messages = [_telegram_message(i, text="T" * 3000) for i in range(1, 41)]

    capped = meta_block._cap_notification_attention(
        agent, _attention_payload(messages)
    )

    spill_path = capped["overflow"]["path"]
    assert spill_path in capped["comment"]


def test_attention_cap_shares_persistent_env_bar(tmp_path, monkeypatch):
    """One env var enforces the upper limit across both notification lanes."""
    agent = _cap_agent(tmp_path)
    messages = [_telegram_message(i, text="T" * 500) for i in range(1, 41)]
    attention = _attention_payload(messages)
    # Tighten the shared env bar below the default; both lanes honor it.
    monkeypatch.setenv(ENV, "1500")

    capped = meta_block._cap_notification_attention(agent, attention)
    assert _attention_chars(capped) <= 1500
    assert capped.get("overflow", {}).get("truncated") is True

    # The persistent lane honors the same tightened bar.
    persistent_agent = SimpleNamespace(
        _working_dir=str(tmp_path),
        _notification_persistent_telegram_message_ids=[],
        _notification_persistent_telegram_last_tool_id=None,
    )
    raw_payload = {
        "notifications": {
            "email": {
                "data": {
                    "count": 1,
                    "email_ids": ["email-1"],
                    "emails": [
                        {
                            "id": "email-1",
                            "from": "human",
                            "subject": "Subject 1",
                            "message": "E" * 5000,
                        }
                    ],
                }
            }
        }
    }
    persistent = meta_block.build_notification_persistent_payload(
        persistent_agent, raw_payload
    )
    assert persistent["notification_persistent"]["overflow"]["truncated"] is True


def test_attention_spill_failure_uses_producer_guidance(tmp_path):
    """Without a workdir the compacted lane still carries a recovery hint."""
    agent = SimpleNamespace(_working_dir=None)
    messages = [_telegram_message(i, text="T" * 3000) for i in range(1, 41)]

    capped = meta_block._cap_notification_attention(
        agent, _attention_payload(messages)
    )

    assert capped["overflow"]["truncated"] is True
    assert capped["overflow"].get("spill_failed") is True
    assert "producer tool" in capped["comment"]
    assert _attention_chars(capped) <= MAX


def test_attention_cap_honors_ceiling(tmp_path, monkeypatch):
    """Env values above the 10k ceiling are clamped, not silently disabled."""
    agent = _cap_agent(tmp_path)
    messages = [_telegram_message(i, text="T" * 3000) for i in range(1, 41)]
    monkeypatch.setenv(ENV, "999999")

    capped = meta_block._cap_notification_attention(
        agent, _attention_payload(messages)
    )
    # Over the clamped ceiling the payload is still capped.
    assert _attention_chars(capped) <= meta_block.NOTIFICATION_ATTENTION_MAX_CHARS_CEILING
    assert capped.get("overflow", {}).get("truncated") is True


def test_build_synthetic_meta_envelope_caps_attention(tmp_path):
    """IDLE path: the synthesized pair's attention axis is capped."""
    agent = _cap_agent(tmp_path)
    messages = [_telegram_message(i, text="T" * 3000) for i in range(1, 41)]

    payload = meta_block.build_notification_payload(_attention_payload(messages))
    envelope = meta_block.build_synthetic_meta_envelope(
        agent, payload, call_id="call_attention_cap_test"
    )

    attention = envelope["agent_meta"]["notifications"]["attention"]
    assert attention.get("overflow", {}).get("truncated") is True
    assert _attention_chars(attention) <= MAX
    assert _spill_files(tmp_path)

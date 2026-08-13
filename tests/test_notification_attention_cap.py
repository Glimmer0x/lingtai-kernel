"""Tests for the 10k character cap on the attention notification lane.

The attention lane (``_meta.agent_meta.notifications.attention``) is re-stamped
on every eligible tool batch and on every IDLE/ASLEEP synthesized pair, so a
busy hub agent (many unread emails plus several IM lanes) could grow context
fast and pay a large per-call cache miss.  The cap shares the
``LINGTAI_NOTIFICATION_MAX_CHARS`` env bar with the persistent lane (single
upper limit across all notification channels, Jason 2026-08-13); over the cap
it spills the full attention lane to ``logs/notification-attention-overflow-<digest>.json``
(content-addressed, so an unchanged oversized lane reuses the same file) and
returns a compacted copy with an ``overflow`` marker that points the agent at
the file (or the producer tool when the spill failed).  The terminal routing
stub is capped strictly and preserves ``message_ids`` (the stable IM routing
identifier) for as long as any routing remains.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
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


# ---------------------------------------------------------------------------
# P1-1: the terminal routing stub is a STRICT cap and preserves message_ids
# ---------------------------------------------------------------------------


def _real_sanitized_telegram_attention() -> tuple[dict, str]:
    """Real Telegram attention after ``sanitize_telegram_notification_after_persistent``.

    Mirrors the persistent-cap test's producer payload; the sanitizer replaces
    the ephemeral ``mcp.telegram`` block with ``data.message_ids`` only, which
    is the stable IM routing identifier the routing stub must preserve.
    """
    messages = [_telegram_message(i, text="T" * 3000) for i in range(1, 41)]
    payload = {
        "notifications": {
            "mcp.telegram": {
                "data": {
                    "count": 1,
                    "previews": [
                        {
                            "from": "Jason",
                            "subject": "telegram message from Jason via main",
                            "platform": "telegram",
                            "conversation_ref": "main:123",
                            "message_ref": messages[-1]["id"],
                            "recent_messages": messages,
                            "latest_incoming": messages[-1],
                        }
                    ],
                }
            }
        }
    }
    meta_block.sanitize_telegram_notification_after_persistent(payload)
    return payload["notifications"], messages[-1]["id"]


def _short_workdir() -> Path:
    """A short absolute workdir so the marker path stays small under low caps.

    The content-addressed spill marker carries the absolute spill path, and a
    long pytest ``tmp_path`` would dominate a 200-char cap; a short dedicated
    dir keeps the routing stub (with ``message_ids``) measurable against it.
    """
    workdir = Path("/tmp") / f"n{os.getpid()}x{os.urandom(2).hex()}"
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def test_real_sanitized_telegram_low_cap_is_strict_and_keeps_message_ids(
    tmp_path, monkeypatch
):
    """P1-1: real sanitized Telegram under a 200-char cap fits STRICTLY.

    The old fallback returned a 430-char stub with the IM ``message_ids``
    dropped; the fixed degradation keeps ``message_ids`` (the routing
    identifier) for as long as any routing remains and enforces the cap on the
    serialized stub.
    """
    workdir = _short_workdir()
    try:
        agent = SimpleNamespace(_working_dir=str(workdir))
        attention, message_id = _real_sanitized_telegram_attention()
        monkeypatch.setenv(ENV, "200")

        capped = meta_block._cap_notification_attention(agent, copy.deepcopy(attention))

        serialized = json.dumps(capped, ensure_ascii=False, sort_keys=True)
        assert len(serialized) <= 200
        assert capped["mcp.telegram"]["data"]["message_ids"] == [message_id]
        assert capped["overflow"]["truncated"] is True
        assert capped["overflow"]["full_chars"] > 200
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def test_real_sanitized_telegram_pathological_cap_degrades_to_marker_only(
    tmp_path, monkeypatch
):
    """P1-1: cap 1 cannot fit anything but the bounded minimal envelope.

    No JSON value serializes to a single character, so the documented terminal
    guard returns the overflow-marker-only envelope: deterministic, bounded,
    and far below the old 434-char over-cap stub.
    """
    agent = _cap_agent(tmp_path)
    attention, _ = _real_sanitized_telegram_attention()
    monkeypatch.setenv(ENV, "1")

    capped = meta_block._cap_notification_attention(agent, copy.deepcopy(attention))

    assert set(capped) == {"overflow"}
    assert capped["overflow"]["truncated"] is True
    assert "comment" not in capped
    assert "mcp.telegram" not in capped
    serialized = json.dumps(capped, ensure_ascii=False, sort_keys=True)
    # Bounded: strictly smaller than the un-capped routing stub (434 chars).
    assert len(serialized) < 250


def test_many_source_structural_overflow_stays_under_default_cap(tmp_path):
    """P1-1: 180+ structural sources never exceed the default 10k cap."""
    agent = _cap_agent(tmp_path)
    attention: dict = {}
    for source in range(180):
        attention[f"mcp.source{source}"] = {
            "data": {
                "count": 9999,
                "email_ids": [f"email-{source}-{i}" for i in range(50)],
                "message_ref": f"ref-{source}-99",
                "event_ids": [f"ev-{source}-{i}" for i in range(30)],
                "ref": f"r-{source}",
                "ref_id": f"rid-{source}",
                "message_ids": [f"msg-{source}-{i}" for i in range(20)],
            }
        }

    capped = meta_block._cap_notification_attention(agent, attention)

    serialized = json.dumps(capped, ensure_ascii=False, sort_keys=True, default=str)
    assert len(serialized) <= MAX
    assert capped.get("overflow", {}).get("truncated") is True


def test_adversarial_structural_values_stay_under_cap(tmp_path, monkeypatch):
    """P1-1: huge counts and huge id lists degrade to a bounded head."""
    agent = _cap_agent(tmp_path)
    attention = {
        "mcp.telegram": {
            "data": {
                "count": 10**30,
                "email_ids": [f"email-{i}" for i in range(10_000)],
                "message_ids": [f"main:123:{i}" for i in range(10_000)],
                "event_ids": [f"ev-{i}" for i in range(10_000)],
                "ref": "ref-" * 5000,
                "ref_id": "rid-" * 5000,
                "message_ref": "mref-" * 5000,
            }
        }
    }
    monkeypatch.setenv(ENV, "2000")

    capped = meta_block._cap_notification_attention(agent, attention)

    serialized = json.dumps(capped, ensure_ascii=False, sort_keys=True, default=str)
    assert len(serialized) <= 2000
    assert capped["overflow"]["truncated"] is True
    # The id lists degrade to the bounded head, keeping the routing identifier.
    assert (
        len(capped["mcp.telegram"]["data"]["message_ids"])
        == meta_block.NOTIFICATION_ATTENTION_ROUTING_ID_HEAD
    )


# ---------------------------------------------------------------------------
# P1-2: content-addressed, exclusive attention spill
# ---------------------------------------------------------------------------


def test_unchanged_attention_reuses_single_spill_file(tmp_path):
    """P1-2: an unchanged oversized lane spills ONCE with a stable marker path.

    The old code re-spilled on every batch (timestamp + suffix loop, -100
    overwritten); the content-addressed name reuses the same file and the two
    markers point at the identical recovery handle.
    """
    agent = _cap_agent(tmp_path)
    messages = [_telegram_message(i, text="T" * 3000) for i in range(1, 41)]
    attention = _attention_payload(messages)

    first = meta_block._cap_notification_attention(agent, copy.deepcopy(attention))
    second = meta_block._cap_notification_attention(agent, copy.deepcopy(attention))

    spill_files = _spill_files(tmp_path)
    assert len(spill_files) == 1
    assert first["overflow"]["path"] == second["overflow"]["path"]
    assert first["overflow"]["path"] == str(spill_files[0])
    spilled = json.loads(spill_files[0].read_text(encoding="utf-8"))
    spilled_messages = spilled["mcp.telegram"]["data"]["previews"][0]["recent_messages"]
    assert spilled_messages[0]["text"] == "T" * 3000


def _preoccupied_spill_name(digest: str, suffix: int | None) -> str:
    if suffix is None:
        return f"notification-attention-overflow-{digest}.json"
    return f"notification-attention-overflow-{digest}-{suffix}.json"


def test_spill_name_exhaustion_never_overwrites_existing_file(tmp_path, monkeypatch):
    """P1-2: when every exclusive name is taken, spill fails without overwriting.

    Pre-occupies the content-addressed name and all 100 suffix fallbacks with a
    DIFFERENT payload; the spill must fail (producer tool guidance) and every
    existing recovery handle must keep its original bytes.
    """
    agent = _cap_agent(tmp_path)
    messages = [_telegram_message(i, text="T" * 3000) for i in range(1, 41)]
    attention = _attention_payload(messages)
    canonical = json.dumps(attention, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:8]

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    occupied: list[Path] = []
    names = [_preoccupied_spill_name(digest, None)] + [
        _preoccupied_spill_name(digest, suffix) for suffix in range(1, 101)
    ]
    for name in names:
        path = logs_dir / name
        path.write_text(json.dumps({"occupied": True}), encoding="utf-8")
        occupied.append(path)

    capped = meta_block._cap_notification_attention(agent, copy.deepcopy(attention))

    assert capped["overflow"].get("spill_failed") is True
    assert "producer tool" in capped["comment"]
    for path in occupied:
        assert json.loads(path.read_text(encoding="utf-8")) == {"occupied": True}


def test_concurrent_writers_same_payload_single_file(tmp_path):
    """P1-2: a two-writer race on the same payload yields ONE intact file."""
    agent = _cap_agent(tmp_path)
    messages = [_telegram_message(i, text="T" * 3000) for i in range(1, 41)]
    attention = _attention_payload(messages)

    def spill_once():
        out = meta_block._cap_notification_attention(agent, copy.deepcopy(attention))
        return out["overflow"]["path"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        paths = list(pool.map(lambda _: spill_once(), range(8)))

    spill_files = _spill_files(tmp_path)
    assert len(spill_files) == 1
    assert len(set(paths)) == 1
    assert paths[0] == str(spill_files[0])
    spilled = json.loads(spill_files[0].read_text(encoding="utf-8"))
    assert spilled["mcp.telegram"]["data"]["previews"][0]["recent_messages"][0]["text"] == "T" * 3000


def test_concurrent_writers_different_payloads_never_lose(tmp_path):
    """P1-2: two different payloads never collide and never overwrite."""
    agent = _cap_agent(tmp_path)
    messages_a = [_telegram_message(i, text="A" * 3000) for i in range(1, 41)]
    messages_b = [_telegram_message(i, text="B" * 3000) for i in range(1, 41)]

    out_a = meta_block._cap_notification_attention(
        agent, copy.deepcopy(_attention_payload(messages_a))
    )
    out_b = meta_block._cap_notification_attention(
        agent, copy.deepcopy(_attention_payload(messages_b))
    )

    assert out_a["overflow"]["path"] != out_b["overflow"]["path"]
    spill_files = _spill_files(tmp_path)
    assert len(spill_files) == 2
    markers = {
        json.loads(path.read_text(encoding="utf-8"))["mcp.telegram"]["data"]["previews"][0][
            "recent_messages"
        ][0]["text"][0]
        for path in spill_files
    }
    assert markers == {"A", "B"}
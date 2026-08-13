"""Doc parity: notification manual + LICC contract describe both lanes.

Round-3 P2: the packaged notification manual and the LICC Notification
Contract must describe the ACTUAL current cap semantics for BOTH the
persistent and attention lanes: the shared ``LINGTAI_NOTIFICATION_MAX_CHARS``
bar with the 2048 floor / 10,000 ceiling, the persistent
``notification-overflow-<ts>.json`` and content-addressed digest8 attention
``notification-attention-overflow-<digest8>.json`` spill namings, and the
capped-by-construction marker-only degradation.  The stale
'sparse and update-driven' wording of LICC item 4 must be gone.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANUAL = ROOT / "src/lingtai/intrinsic_skills/notification-manual/SKILL.md"
CONTRACT = ROOT / "src/lingtai/services/LICC_NOTIFICATION_CONTRACT.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_both_docs_mention_both_overflow_spill_namings() -> None:
    """Persistent (timestamp) and attention (content-addressed digest8) spill
    names are documented in both the manual and the LICC contract."""
    manual = _text(MANUAL)
    contract = _text(CONTRACT)
    for label, text in (("manual", manual), ("contract", contract)):
        assert "notification-overflow-" in text, label
        assert "notification-attention-overflow-" in text, label


def test_both_docs_mention_shared_env_bar_with_floor_and_ceiling() -> None:
    """Both documents name the shared env bar and its floor 2048 / ceiling
    10,000 clamp."""
    manual = _text(MANUAL)
    contract = _text(CONTRACT)
    for label, text in (("manual", manual), ("contract", contract)):
        assert "LINGTAI_NOTIFICATION_MAX_CHARS" in text, label
        assert "2048" in text, label
        # "10,000" and "10000" both spell the ceiling.
        assert "10000" in text.replace(",", ""), label


def test_licc_item4_no_longer_claims_sparse_update_driven_attachment() -> None:
    """LICC item 4 now describes copy-to-every-carrier ACTIVE semantics; the
    stale 'sparse and update-driven' wording (and 'only on first appearance')
    must not appear anywhere in the contract."""
    contract = _text(CONTRACT)
    assert "only on first appearance" not in contract
    assert "sparse and update-driven" not in contract


def test_manual_describes_both_lanes_not_persistent_only() -> None:
    """The manual's cap section covers the attention lane too (marker-only
    degradation, path omission, content-addressed spill)."""
    manual = _text(MANUAL)
    assert "notification.attention" in manual
    assert "marker-only" in manual or "marker only" in manual
    assert "path_omitted" in manual


def test_contract_mentions_path_omitted_final_guard_and_digest8_spill() -> None:
    """The LICC contract records the capped-by-construction terminal guard
    (path stripped when needed) and the digest8 content-addressed spill."""
    contract = _text(CONTRACT)
    assert "path_omitted" in contract
    assert "digest8" in contract

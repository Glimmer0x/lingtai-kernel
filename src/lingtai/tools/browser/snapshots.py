"""Bounded in-memory snapshot identity and provenance state."""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone

from .extractor import Block, ExtractedDocument


@dataclass(frozen=True, slots=True)
class LinkItem:
    ref: str
    text: str
    url: str
    # Full canonical target is the source of truth; ``url`` is display-only.
    # Refs are minted again when any success response is emitted.
    target: str = ""


@dataclass(frozen=True, slots=True)
class Snapshot:
    snapshot_id: str
    source_sha256: str
    requested_url: str
    final_url: str
    http_status: int
    content_type: str
    title: str
    retrieved_at: str
    redirect_chain: list[str]
    blocks: list[Block]
    links: list[LinkItem]
    extract_mode: str
    warnings: list[str]


class InMemorySnapshotStore:
    """LRU snapshot store; eviction is observable as a stale-cursor failure."""

    def __init__(self, max_snapshots: int = 16) -> None:
        if not isinstance(max_snapshots, int) or isinstance(max_snapshots, bool) or max_snapshots < 1:
            raise ValueError("max_snapshots must be positive")
        self.max_snapshots = max_snapshots
        self._items: OrderedDict[str, Snapshot] = OrderedDict()
        self._counter = 0

    def put(
        self,
        *,
        raw_bytes: bytes,
        fetched_url: str,
        final_url: str,
        http_status: int,
        content_type: str,
        extracted: ExtractedDocument,
        links: list[LinkItem],
        extract_mode: str,
        redirect_chain: list[str],
    ) -> Snapshot:
        self._counter += 1
        digest = hashlib.sha256(raw_bytes).hexdigest()
        snapshot = Snapshot(
            snapshot_id=f"snap_{digest[:12]}_{self._counter:04d}",
            source_sha256=digest,
            requested_url=fetched_url,
            final_url=final_url,
            http_status=http_status,
            content_type=content_type,
            title=extracted.title,
            retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            redirect_chain=list(redirect_chain),
            blocks=list(extracted.blocks),
            links=list(links),
            extract_mode=extract_mode,
            warnings=list(extracted.warnings),
        )
        self._items[snapshot.snapshot_id] = snapshot
        self._items.move_to_end(snapshot.snapshot_id)
        while len(self._items) > self.max_snapshots:
            self._items.popitem(last=False)
        return snapshot

    def get(self, snapshot_id: str) -> Snapshot | None:
        snapshot = self._items.get(snapshot_id)
        if snapshot is not None:
            self._items.move_to_end(snapshot_id)
        return snapshot

    def __len__(self) -> int:
        return len(self._items)


def compute_source_sha256(raw_bytes: bytes) -> str:
    return hashlib.sha256(raw_bytes).hexdigest()

"""Bounded per-Agent link reference store."""
from __future__ import annotations

import hashlib
from collections import OrderedDict


class RefStore:
    def __init__(self, max_refs: int = 256) -> None:
        if not isinstance(max_refs, int) or isinstance(max_refs, bool) or max_refs < 1:
            raise ValueError("max_refs must be positive")
        self.max_refs = max_refs
        self._url_to_ref: dict[str, str] = {}
        self._refs: OrderedDict[str, str] = OrderedDict()

    def add_link_ref(self, url: str) -> str:
        ref = self._url_to_ref.get(url)
        if ref is None:
            ref = "ln_" + hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
            self._url_to_ref[url] = ref
            self._refs[ref] = url
        self._refs.move_to_end(ref)
        while len(self._refs) > self.max_refs:
            old_ref, old_url = self._refs.popitem(last=False)
            if self._url_to_ref.get(old_url) == old_ref:
                del self._url_to_ref[old_url]
        return ref

    def resolve_link_ref(self, ref: object) -> str | None:
        if not isinstance(ref, str):
            return None
        url = self._refs.get(ref)
        if url is not None:
            self._refs.move_to_end(ref)
        return url

    def __len__(self) -> int:
        return len(self._refs)

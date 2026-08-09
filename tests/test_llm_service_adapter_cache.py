"""Regression tests for LLMService.get_adapter adapter-cache concurrency.

Issue lingtai-kernel#739: the lock-free fast-path scan of ``self._adapters``
(``base_url=None``) raced with a concurrent insert from the locked slow path,
raising ``RuntimeError: dictionary changed size during iteration``. The scan is
now snapshot-based and follows a documented deterministic preference:

1. the ``(provider, None)`` entry,
2. the entry matching the provider's configured default base_url,
3. first match by sorted cache key (stable tie-break).
"""

from __future__ import annotations

import sys
import threading

from lingtai.llm.service import LLMService


def _register_identity_adapter(provider: str) -> None:
    """Register a hermetic factory returning a fresh opaque object per call."""
    LLMService.register_adapter(provider, lambda **kwargs: object())


def _make_service(
    provider: str = "p",
    *,
    base_url: str | None = None,
    defaults: dict | None = None,
) -> LLMService:
    """Build an LLMService whose adapter cache the test controls exactly.

    The constructor seeds one ``(provider, base_url)`` entry; tests that need
    a precise cache shape call :meth:`_make_service` and then replace
    ``svc._adapters`` contents themselves.
    """
    _register_identity_adapter(provider)
    svc = LLMService(
        provider=provider,
        model="m",
        api_key="k",
        base_url=base_url,
        key_resolver=lambda p: "k",
        provider_defaults=defaults or {},
    )
    svc._adapters.clear()
    return svc


# ---------------------------------------------------------------------------
# Regression: lock-free fast-path scan vs concurrent insert (the #739 crash)
# ---------------------------------------------------------------------------


def test_get_adapter_scan_race_with_concurrent_insert():
    """A base_url=None scan must never raise under a concurrent cache insert.

    On the unfixed code this reproduces ``RuntimeError: dictionary changed
    size during iteration``: the fast path iterates the live dict while the
    slow path inserts a fresh ``(provider, base_url)`` key under the lock.
    """
    _register_identity_adapter("race-other")
    _register_identity_adapter("race-b")
    svc = LLMService(
        provider="race-other",
        model="m",
        api_key="k",
        key_resolver=lambda p: "k",
    )
    svc._adapters.clear()
    # Every reader scan walks thousands of NON-matching entries before hitting
    # the single match at the end, so each get_adapter("race-a") call does a
    # long full-dict iteration (the unfixed fast-path scan is the race window).
    for i in range(1500):
        svc._adapters[("race-other", f"http://x/{i}")] = object()
    svc._adapters[("race-a", "http://end")] = object()

    errors: list[BaseException] = []
    errors_lock = threading.Lock()
    n_readers = 4
    n_writers = 2
    old_interval = sys.getswitchinterval()

    def reader() -> None:
        try:
            for _ in range(1200):
                svc.get_adapter("race-a")  # no base_url -> scans the cache
        except BaseException as exc:  # pragma: no cover - failure path
            with errors_lock:
                errors.append(exc)

    def writer() -> None:
        try:
            for i in range(200):
                # Fresh key each time -> slow path creates + inserts concurrently.
                svc.get_adapter("race-b", f"http://w/{i}")
        except BaseException as exc:  # pragma: no cover - failure path
            with errors_lock:
                errors.append(exc)

    barrier = threading.Barrier(n_readers + n_writers)
    threads = []
    try:
        # Dense thread switches make the mid-scan insert window much likelier.
        sys.setswitchinterval(1e-6)
        for _ in range(n_readers):
            threads.append(threading.Thread(target=lambda: (barrier.wait(), reader())))
        for _ in range(n_writers):
            threads.append(threading.Thread(target=lambda: (barrier.wait(), writer())))
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)
    finally:
        sys.setswitchinterval(old_interval)

    assert not errors, f"get_adapter raced on concurrent insert: {errors!r}"


def test_get_adapter_single_creation_under_contention():
    """Double-checked locking still guarantees one adapter per cache key."""
    _register_identity_adapter("p")
    created: list[object] = []
    created_lock = threading.Lock()

    def counting_factory(**kwargs):
        with created_lock:
            created.append(object())
            return created[-1]

    LLMService.register_adapter("newprov", counting_factory)
    svc = _make_service()
    n = 8
    results: list[object] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker() -> None:
        barrier.wait()
        adapter = svc.get_adapter("newprov")
        with results_lock:
            results.append(adapter)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert len(created) == 1, f"factory ran {len(created)} times instead of once"
    assert all(r is created[0] for r in results)


# ---------------------------------------------------------------------------
# Deterministic preference for base_url=None lookups with multiple cached URLs
# ---------------------------------------------------------------------------


def test_get_adapter_prefers_none_key_entry():
    """Rule 1: the (provider, None) entry wins over any URL entry."""
    svc = _make_service()
    none_adapter = object()
    url_adapter = object()
    for order in ("none_first", "url_first"):
        svc._adapters.clear()
        if order == "none_first":
            svc._adapters[("p", None)] = none_adapter
            svc._adapters[("p", "http://b")] = url_adapter
        else:
            svc._adapters[("p", "http://b")] = url_adapter
            svc._adapters[("p", None)] = none_adapter
        assert svc.get_adapter("p") is none_adapter, order


def test_get_adapter_prefers_configured_default_base_url():
    """Rule 2: the entry matching the provider's configured default wins."""
    svc = _make_service(defaults={"p": {"base_url": "http://b"}})
    a_adapter = object()
    b_adapter = object()
    for order in ("a_first", "b_first"):
        svc._adapters.clear()
        if order == "a_first":
            svc._adapters[("p", "http://a")] = a_adapter
            svc._adapters[("p", "http://b")] = b_adapter
        else:
            svc._adapters[("p", "http://b")] = b_adapter
            svc._adapters[("p", "http://a")] = a_adapter
        assert svc.get_adapter("p") is b_adapter, order


def test_get_adapter_sorted_tiebreak_is_stable():
    """Rule 3: with no None entry or default match, sorted-key order wins."""
    svc = _make_service()  # no provider defaults -> no default base_url
    z_adapter = object()
    a_adapter = object()
    for order in ("z_first", "a_first"):
        svc._adapters.clear()
        if order == "z_first":
            svc._adapters[("p", "http://z")] = z_adapter
            svc._adapters[("p", "http://a")] = a_adapter
        else:
            svc._adapters[("p", "http://a")] = a_adapter
            svc._adapters[("p", "http://z")] = z_adapter
        assert svc.get_adapter("p") is a_adapter, order


def test_get_adapter_exact_key_still_wins():
    """An explicit base_url lookup never falls back to the provider scan."""
    svc = _make_service()
    none_adapter = object()
    a_adapter = object()
    svc._adapters[("p", None)] = none_adapter
    svc._adapters[("p", "http://a")] = a_adapter
    assert svc.get_adapter("p", "http://a") is a_adapter
    assert svc.get_adapter("p") is none_adapter

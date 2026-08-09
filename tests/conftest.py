"""Shared pytest fixtures for LingTai kernel tests."""

from __future__ import annotations

import pytest

from ._agent_dir_helpers import make_agent_dir as _make_agent_dir


@pytest.fixture
def make_agent_dir():
    """Factory fixture: create a minimal agent working dir.

    Returns the :func:`tests._agent_dir_helpers.make_agent_dir` callable so a
    single test can build several agent dirs with different shapes (heartbeat,
    human, mailbox, …).
    """
    return _make_agent_dir


@pytest.fixture(autouse=True)
def _isolate_cache_miss_budget_env(monkeypatch):
    """Keep the suite hermetic w.r.t. the live cache-miss budget env override.

    ``meta_block._resolve_cache_miss_budget`` reads ``LINGTAI_CACHE_MISS_BUDGET``
    from ``os.environ`` at every budget resolution, so an ambient value (an
    operator's shell, or a LingTai agent's own ``env_file``) would otherwise
    leak into every budget assertion.  Tests that exercise the override opt back
    in with ``monkeypatch.setenv``.
    """

    monkeypatch.delenv("LINGTAI_CACHE_MISS_BUDGET", raising=False)


@pytest.fixture(autouse=True)
def _isolate_notification_dismiss_guards():
    """Keep generic notification-dismiss guard registration test-local."""

    from lingtai.kernel.notifications import _GENERIC_DISMISS_GUARDED

    snapshot = dict(_GENERIC_DISMISS_GUARDED)
    yield
    _GENERIC_DISMISS_GUARDED.clear()
    _GENERIC_DISMISS_GUARDED.update(snapshot)


@pytest.fixture(autouse=True)
def _reset_package_logging():
    """Keep stdlib-logging handler state from leaking across tests.

    ``setup_logging``/``get_logger`` configure a process-global "lingtai"
    logger; without a reset, a FileHandler attached by one test would stay
    attached for every subsequent test in the run (writing to a stale path).
    """

    from lingtai.kernel.logging import reset_logging

    reset_logging()
    yield
    reset_logging()

"""Tests for lingtai.kernel.logging: file logging, idempotency, rotation."""
from __future__ import annotations

import logging

import pytest

from lingtai.kernel import logging as kernel_logging
from lingtai.kernel.logging import (
    get_logger,
    reset_logging,
    setup_logging,
)


@pytest.fixture(autouse=True)
def _clean_logger_state():
    reset_logging()
    yield
    reset_logging()


def test_setup_logging_creates_agent_log(tmp_path):
    setup_logging(log_dir=tmp_path)
    get_logger().warning("hello from the kernel")

    log_file = tmp_path / "agent.log"
    assert log_file.is_file()
    assert "hello from the kernel" in log_file.read_text(encoding="utf-8")


def test_setup_logging_idempotent_no_duplicate_file_handler(tmp_path):
    setup_logging(log_dir=tmp_path)
    setup_logging(log_dir=tmp_path)  # second call must not stack a second FileHandler

    get_logger().warning("only once")
    text = (tmp_path / "agent.log").read_text(encoding="utf-8")
    assert text.count("only once") == 1

    file_handlers = [
        h for h in logging.getLogger("lingtai").handlers
        if isinstance(h, logging.FileHandler)
    ]
    assert len(file_handlers) == 1


def test_verbose_reconfigures_console_level():
    setup_logging()  # default INFO console
    setup_logging(verbose=True)  # must raise the console handler to DEBUG

    logger = logging.getLogger("lingtai")
    console = next(
        h for h in logger.handlers
        if isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.FileHandler)
    )
    assert console.level == logging.DEBUG


def test_exc_info_traceback_lands_in_file(tmp_path):
    setup_logging(log_dir=tmp_path)
    try:
        raise RuntimeError("claim failure diagnostic")
    except RuntimeError:
        get_logger().warning("failed to write claimed message", exc_info=True)

    text = (tmp_path / "agent.log").read_text(encoding="utf-8")
    assert "failed to write claimed message" in text
    assert "RuntimeError: claim failure diagnostic" in text
    assert "Traceback (most recent call last)" in text


def test_rotation_caps_file_size(tmp_path, monkeypatch):
    monkeypatch.setattr(kernel_logging, "_FILE_MAX_BYTES", 512)
    monkeypatch.setattr(kernel_logging, "_FILE_BACKUP_COUNT", 2)
    setup_logging(log_dir=tmp_path)

    logger = get_logger()
    for i in range(200):
        logger.warning("rotating payload %s %s", i, "x" * 64)

    assert (tmp_path / "agent.log").is_file()
    assert (tmp_path / "agent.log.1").is_file()  # a rotated backup exists


def test_reset_logging_detaches_handlers(tmp_path):
    setup_logging(log_dir=tmp_path)
    logger = logging.getLogger("lingtai")
    assert len(logger.handlers) == 2  # console + file

    reset_logging()
    assert len(logger.handlers) == 0

    # get_logger() lazily recreates the default (console-only) setup.
    assert len(get_logger().handlers) == 1

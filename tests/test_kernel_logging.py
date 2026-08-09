"""Tests for lingtai.kernel.logging (package logger configuration)."""
import logging

from lingtai.kernel.logging import get_logger, setup_logging


def test_setup_logging_repeated_calls_do_not_duplicate_file_handlers(tmp_path):
    name = "lingtai-test-logging-idempotent"
    logger = setup_logging(log_dir=tmp_path, logger_name=name)
    try:
        assert setup_logging(log_dir=tmp_path, logger_name=name) is logger

        file_handlers = [h for h in logger.handlers if isinstance(h, logging.FileHandler)]
        stream_handlers = [
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
        ]
        assert len(file_handlers) == 1
        assert len(stream_handlers) == 1
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


def test_get_logger_console_default_unchanged(monkeypatch):
    import lingtai.kernel.logging as kernel_logging

    monkeypatch.setattr(kernel_logging, "_logger", None)
    logger = get_logger()
    assert isinstance(logger, logging.Logger)
    assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)
    assert not any(isinstance(h, logging.FileHandler) for h in logger.handlers)

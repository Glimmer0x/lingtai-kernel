"""Package-internal logging for lingtai.

One process, one agent: ``setup_logging`` configures the process-global
``"lingtai"`` logger (see the workdir lease / ``_check_duplicate_process``
exclusion in ``lingtai.cli``). Every module binds the *same* logger object via
``get_logger()``, so handlers added here are visible to all call sites
regardless of import order.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_logger: logging.Logger | None = None

_CONSOLE_FMT = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
_FILE_FMT = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s %(module)s: %(message)s"
)
# Rotation keeps a long-lived daemon from growing agent.log unboundedly.
_FILE_MAX_BYTES = 5 * 1024 * 1024
_FILE_BACKUP_COUNT = 3


def setup_logging(
    verbose: bool = False,
    log_dir: Path | str | None = None,
    logger_name: str = "lingtai",
) -> logging.Logger:
    """Initialize the package logger. Idempotent; safe to re-invoke.

    Args:
        verbose: If True, set console to DEBUG; otherwise INFO.
        log_dir: Directory for log files. None = no file logging.
        logger_name: Logger name (default: "lingtai").
    """
    global _logger
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.DEBUG)

    # Reuse the existing console handler (if any) instead of stacking a new
    # one on every call, and honor a re-invocation with verbose=True.
    console = next(
        (
            h
            for h in logger.handlers
            if isinstance(h, logging.StreamHandler)
            and not isinstance(h, logging.FileHandler)
        ),
        None,
    )
    if console is None:
        console = logging.StreamHandler()
        console.setFormatter(_CONSOLE_FMT)
        logger.addHandler(console)
    console.setLevel(logging.DEBUG if verbose else logging.INFO)

    if log_dir is not None:
        target = Path(log_dir).resolve() / "agent.log"
        # Guard against duplicate FileHandlers when setup_logging() is invoked
        # more than once with the same log_dir (tests, refresh boots in
        # process, future callers).
        if not any(
            isinstance(h, logging.FileHandler)
            and Path(getattr(h, "baseFilename", "")).resolve() == target
            for h in logger.handlers
        ):
            target.parent.mkdir(parents=True, exist_ok=True)
            fh = RotatingFileHandler(
                target,
                maxBytes=_FILE_MAX_BYTES,
                backupCount=_FILE_BACKUP_COUNT,
            )
            fh.setLevel(logging.DEBUG)
            fh.setFormatter(_FILE_FMT)
            logger.addHandler(fh)

    _logger = logger
    return logger


def reset_logging() -> None:
    """Detach and close all handlers from the package logger.

    Intended for tests and teardown so handler state cannot leak across test
    cases or processes. ``get_logger()`` lazily recreates the default setup
    afterwards.
    """
    global _logger
    if _logger is not None:
        for handler in list(_logger.handlers):
            handler.close()
            _logger.removeHandler(handler)
        _logger = None


def get_logger() -> logging.Logger:
    """Get the package logger. Creates a default if setup_logging() was not called."""
    global _logger
    if _logger is None:
        _logger = setup_logging()
    return _logger

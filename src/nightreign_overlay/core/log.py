"""Logging setup.

Modules obtain a logger with ``log = get_logger(__name__)``; everything below the ``nightreign_overlay``
namespace is written to the console and to a daily rotating file in the user log directory.
"""

from __future__ import annotations

import logging
import sys
import threading
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from types import TracebackType

ROOT_LOGGER_NAME = "nightreign_overlay"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    """Configure console + rotating file handlers and route uncaught exceptions to the log."""
    root = logging.getLogger(ROOT_LOGGER_NAME)
    root.handlers.clear()
    root.propagate = False
    set_log_level(level)

    formatter = logging.Formatter(_FORMAT)

    # Windowed PyInstaller builds have no stderr.
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(formatter)
        root.addHandler(console)

    file_handler = TimedRotatingFileHandler(
        log_dir / "app.log", when="midnight", backupCount=14, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    _install_exception_hooks()


def set_log_level(level: str) -> None:
    logging.getLogger(ROOT_LOGGER_NAME).setLevel(level if level in LOG_LEVELS else "INFO")


def _install_exception_hooks() -> None:
    log = get_logger(ROOT_LOGGER_NAME)

    def excepthook(exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Uncaught exception", exc_info=(exc_type, exc, tb))

    def thread_excepthook(args: threading.ExceptHookArgs) -> None:
        if args.exc_value is not None:
            log.critical(
                "Uncaught exception in thread %s",
                args.thread.name if args.thread else "?",
                exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            )

    sys.excepthook = excepthook
    threading.excepthook = thread_excepthook

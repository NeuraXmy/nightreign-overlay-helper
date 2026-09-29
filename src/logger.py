from logging import getLogger, StreamHandler, Formatter, DEBUG, INFO, WARNING, ERROR, CRITICAL
import os
from datetime import datetime
import traceback

from src.common import get_appdata_path

LOG_DIR = get_appdata_path("logs")

_logger = None

def setup_logger(level: int = INFO):
    handler = StreamHandler()
    handler.setFormatter(Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger = getLogger()
    logger.setLevel(level)
    logger.addHandler(handler)
    logger.propagate = False
    os.makedirs(LOG_DIR, exist_ok=True)
    date = datetime.now().strftime("%Y-%m-%d")
    file_handler = StreamHandler(open(os.path.join(LOG_DIR, f"{date}.log"), "a", encoding="utf-8"))
    file_handler.setFormatter(Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(file_handler)
    return logger

def set_log_level(level: int):
    global _logger
    if _logger is None:
        _logger = setup_logger(level)
    else:
        _logger.setLevel(level)

def is_debug_enabled() -> bool:
    return _logger is not None and _logger.isEnabledFor(DEBUG)

def debug(msg: str):
    global _logger
    if _logger is None:
        _logger = setup_logger()
    _logger.debug(msg)

def info(msg: str):
    global _logger
    if _logger is None:
        _logger = setup_logger()
    _logger.info(msg)

def warning(msg: str):
    global _logger
    if _logger is None:
        _logger = setup_logger()
    _logger.warning(msg)

def error(msg: str, print_trace: bool = True):
    global _logger
    if _logger is None:
        _logger = setup_logger()
    _logger.error(msg)
    if print_trace:
        trace = traceback.format_exc()
        _logger.error(trace)



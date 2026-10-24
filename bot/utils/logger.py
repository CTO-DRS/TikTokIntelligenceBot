"""Logging bootstrap for the whole application."""
from __future__ import annotations

import logging
import logging.config

from config.logging_config import LOGGING_CONFIG, LOG_DIR

_CONFIGURED = False


def setup_logging(level: str = "INFO") -> None:
    """Configure root logging once (idempotent)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:  # read-only FS → console only
        cfg = dict(LOGGING_CONFIG)
        cfg["handlers"] = {"console": cfg["handlers"]["console"]}
        cfg["root"]["handlers"] = ["console"]
        cfg["root"]["level"] = (level or "INFO").upper()
        logging.config.dictConfig(cfg)
        _CONFIGURED = True
        return
    cfg = dict(LOGGING_CONFIG)
    cfg["root"]["level"] = (level or "INFO").upper()
    logging.config.dictConfig(cfg)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

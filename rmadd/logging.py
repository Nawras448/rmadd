"""File-based logging setup for rmadd."""

import logging
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DIR = Path.home() / ".local" / "share" / "rmadd" / "logs"


def setup_logging(level: str = "INFO") -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / "app.log"
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=LOG_FORMAT,
        handlers=[logging.FileHandler(str(log_file))],
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
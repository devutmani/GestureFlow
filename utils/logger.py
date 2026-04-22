"""
utils/logger.py
───────────────
Centralised logging for GestureFlow.
Logs go to console (coloured) and optionally to a rotating file.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from colorama import Fore, Style, init as colorama_init

colorama_init(autoreset=True)


# ── Colour map for console ────────────────────────────────────────────────────
LEVEL_COLOURS = {
    logging.DEBUG:    Fore.CYAN,
    logging.INFO:     Fore.GREEN,
    logging.WARNING:  Fore.YELLOW,
    logging.ERROR:    Fore.RED,
    logging.CRITICAL: Fore.MAGENTA,
}


class ColouredFormatter(logging.Formatter):
    """Add ANSI colour codes to console log records."""

    FMT = "%(asctime)s  %(levelname)-8s  %(name)s  │  %(message)s"
    DATE_FMT = "%H:%M:%S"

    def format(self, record: logging.LogRecord) -> str:
        colour = LEVEL_COLOURS.get(record.levelno, "")
        formatter = logging.Formatter(
            f"{colour}{self.FMT}{Style.RESET_ALL}", datefmt=self.DATE_FMT
        )
        return formatter.format(record)


def get_logger(name: str) -> logging.Logger:
    """
    Return a logger that writes to:
      • stdout   – with colours
      • log file – plain text (if LOG_TO_FILE is True in settings)
    """
    # Import here to avoid circular imports at module level
    from config.settings import LOG_LEVEL, LOG_TO_FILE, LOG_DIR

    logger = logging.getLogger(name)

    # Avoid adding duplicate handlers if called multiple times
    if logger.handlers:
        return logger

    level = getattr(logging, LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(level)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(level)
    ch.setFormatter(ColouredFormatter())
    logger.addHandler(ch)

    # File handler (optional)
    if LOG_TO_FILE:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_path = os.path.join(LOG_DIR, "gestureflow.log")
        fh = RotatingFileHandler(
            log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(level)
        fh.setFormatter(
            logging.Formatter(
                "%(asctime)s  %(levelname)-8s  %(name)s  │  %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(fh)

    return logger

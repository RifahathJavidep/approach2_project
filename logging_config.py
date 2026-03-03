"""
Centralized logging configuration for PRISM.

Sets up:
  - Console handler  : INFO level, coloured prefix
  - File handler     : DEBUG level, full detail → logs/prism.log (rotates at 10 MB)

Usage:
    from logging_config import setup_logging
    setup_logging()          # default log level INFO
    setup_logging("DEBUG")   # verbose
"""
import logging
import logging.handlers
import os
from pathlib import Path

LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOG_DIR / "prism.log"

CONSOLE_FORMAT = "%(asctime)s [%(levelname)s] %(name)s — %(message)s"
FILE_FORMAT    = "%(asctime)s [%(levelname)s] %(name)s (%(filename)s:%(lineno)d) — %(message)s"
DATE_FORMAT    = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """
    Configure root logger with console + rotating file handlers.
    Safe to call multiple times — handlers are not duplicated.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()

    # Don't add handlers twice (e.g. if called from both app.py and celery_app.py)
    if root.handlers:
        return

    root.setLevel(logging.DEBUG)  # let handlers decide their own floor

    # ── Console handler ───────────────────────────────────────────
    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(console)

    # ── Rotating file handler (10 MB × 5 backups) ─────────────────
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(file_handler)

    # Silence noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "boto3", "botocore",
                  "s3transfer", "dspy", "openai", "groq"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        f"Logging initialised — console: {level.upper()} | file: {LOG_FILE}"
    )

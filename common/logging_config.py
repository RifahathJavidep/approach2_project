"""
Logging Setup — rotating file handler + console handler for PRISM.

Usage:
    from common.logging_config import setup_logging
    setup_logging()           # INFO to console, DEBUG to file
    setup_logging("DEBUG")    # verbose console output
"""
import logging
import logging.handlers
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"
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

    if any(getattr(h, "_prism_handler", False) for h in root.handlers):
        return

    root.setLevel(logging.DEBUG)

    console = logging.StreamHandler()
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=DATE_FORMAT))
    console._prism_handler = True
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(FILE_FORMAT, datefmt=DATE_FORMAT))
    file_handler._prism_handler = True
    root.addHandler(file_handler)

    for noisy in ("httpx", "httpcore", "urllib3", "boto3", "botocore",
                  "s3transfer", "dspy", "openai", "groq"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    logging.getLogger(__name__).info(
        "Logging initialised — console: %s | file: %s", level.upper(), LOG_FILE
    )

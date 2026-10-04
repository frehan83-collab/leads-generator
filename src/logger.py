"""
Centralised logging configuration.
Logs to both console and a rotating file.

Formats (LOG_FORMAT env or setup_logging(fmt=...)):
- "pretty" (default): colored console + human-readable file
- "json": one JSON object per line on both handlers (for log aggregation)
"""

import json
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import colorlog


class JsonFormatter(logging.Formatter):
    """Single-line JSON records: ts, level, logger, msg (+ exception)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO", fmt: str = None) -> None:
    fmt = (fmt or os.getenv("LOG_FORMAT", "pretty")).lower()
    as_json = fmt == "json"

    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "leads_generator.log"

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Idempotent: don't stack duplicate handlers on repeated calls.
    if any(isinstance(h, colorlog.StreamHandler) for h in root.handlers):
        return

    if as_json:
        console = logging.StreamHandler()
        console.setFormatter(JsonFormatter())
    else:
        # Console handler with colours
        console = colorlog.StreamHandler()
        console.setFormatter(
            colorlog.ColoredFormatter(
                "%(log_color)s%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%H:%M:%S",
                log_colors={
                    "DEBUG": "cyan",
                    "INFO": "green",
                    "WARNING": "yellow",
                    "ERROR": "red",
                    "CRITICAL": "bold_red",
                },
            )
        )
    root.addHandler(console)

    # Rotating file handler (5 MB max, keep 3 backups)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    if as_json:
        file_handler.setFormatter(JsonFormatter())
    else:
        file_handler.setFormatter(
            logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    root.addHandler(file_handler)

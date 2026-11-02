"""Structured Logging Configuration for KeyFlint."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_entry["extra"] = record.extra
        return json.dumps(log_entry, default=str)


def configure_logging(log_level: str = "INFO", use_json: bool = False) -> None:
    """Configures root logger with appropriate handlers and formatters."""
    level = getattr(logging, log_level.upper(), logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)

    # Remove existing handlers to avoid duplicates
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    if use_json:
        handler.setFormatter(JSONFormatter())
    else:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)

    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Convenience getter for namespaced loggers."""
    return logging.getLogger(f"keyflint.{name}")

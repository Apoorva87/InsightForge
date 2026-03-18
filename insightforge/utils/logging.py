"""Logging setup — Rich-backed console logger with optional JSON format."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from rich.console import Console
from rich.logging import RichHandler


_console = Console(stderr=True)


def setup_logging(level: str = "INFO", format: str = "text") -> None:
    """Configure root logger.

    Args:
        level: Log level string, e.g. "DEBUG", "INFO", "WARNING".
        format: "text" for Rich console output; "json" for structured JSON lines.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    if format == "json":
        _setup_json_logging(log_level)
    else:
        _setup_rich_logging(log_level)


def _setup_rich_logging(level: int) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=_console, rich_tracebacks=True, markup=True)],
    )


def _setup_json_logging(level: int) -> None:
    """Minimal JSON log lines — one JSON object per line to stdout."""
    import json

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload = {
                "ts": self.formatTime(record),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.

    Args:
        name: Logger name, typically __name__ of the calling module.
    """
    return logging.getLogger(name)

"""Verbose logs on stderr and, optionally, in a file.

Levels, from the CLI flags or the environment (for `cli ui` and other entry points):

* `-v` / `COPILOT_LOG_LEVEL=INFO`: one line per trace span (decisions, retrieval, tools, model calls),
  the retrieval ranking with every signal, and the passages that went to the model
* `-vv` / `COPILOT_LOG_LEVEL=DEBUG`: also every retrieval candidate before reranking, and the full
  messages sent to the chat model with its raw reply
* `COPILOT_LOG_FILE=runs/logs/copilot.log`: the same lines in a file (appended)

Log lines pass through the trace redaction filter, so API keys and account IDs are masked.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .trace import redact_text

LOGGER = "campus_copilot"
FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-5s %(name)s: %(message)s"
DATEFMT = "%H:%M:%S"


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = None
        return True


def level_from(verbosity: int = 0) -> int:
    if verbosity >= 2:
        return logging.DEBUG
    if verbosity == 1:
        return logging.INFO
    name = os.environ.get("COPILOT_LOG_LEVEL", "").strip().upper()
    return getattr(logging, name, logging.WARNING) if name else logging.WARNING


def setup(verbosity: int = 0, file: str | None = None) -> logging.Logger:
    """Configure the `campus_copilot` logger once; later calls only change the level."""
    logger = logging.getLogger(LOGGER)
    logger.setLevel(level_from(verbosity))
    logger.propagate = False
    if not getattr(logger, "_copilot_configured", False):
        formatter = logging.Formatter(FORMAT, DATEFMT)
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        console.addFilter(RedactFilter())
        logger.addHandler(console)
        path = file or os.environ.get("COPILOT_LOG_FILE")
        if path:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(path, encoding="utf-8")
            handler.setFormatter(formatter)
            handler.addFilter(RedactFilter())
            logger.addHandler(handler)
        logger._copilot_configured = True  # type: ignore[attr-defined]
    return logger


def span_line(row: dict) -> str:
    """A compact one-line view of a trace span for the INFO log."""
    keys = ("route", "action", "confidence", "tool", "model", "tokens_in", "tokens_out", "mode", "hits", "kind",
            "gate", "query.rewritten", "kept", "dropped", "reused", "stub", "error")
    extras = [f"{k}={row[k]}" for k in keys if row.get(k) not in (None, "", [], {})]
    return f"span {row['span']:<16} {row['ms']:>8.1f} ms  " + " ".join(extras)

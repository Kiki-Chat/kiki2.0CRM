"""Structured (JSON-line) logging (Item 4 — applied by configure_logging()).

One JSON object per log line: ts, level, logger, msg, the current request_id (when
inside a request), and a curated set of access-log extras (method/path/status/
duration_ms). JSON lines are trivially greppable and parseable by log tooling, and
the shared request_id ties every line in a request together.

``configure_logging`` is called from ``main.py`` only when
``settings.observability_enabled`` is true, so default behaviour is unchanged.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.core.observability import request_id_var

# LogRecord attributes we surface as structured fields when present (set via
# ``logger.info(..., extra={...})``). Everything else stays out of the line.
_EXTRA_FIELDS = ("method", "path", "status", "duration_ms", "org_id", "user_id")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        data: dict = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = request_id_var.get()
        if rid:
            data["request_id"] = rid
        for field in _EXTRA_FIELDS:
            if (val := getattr(record, field, None)) is not None:
                data[field] = val
        if record.exc_info:
            data["exc"] = self.formatException(record.exc_info)
        return json.dumps(data, default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Route the root logger through the JSON formatter (idempotent)."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # uvicorn's access logger is redundant once our middleware logs requests.
    logging.getLogger("uvicorn.access").handlers = []

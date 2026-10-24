import json
import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

# Extra fields copied onto every JSON log line when passed via `extra=`.
_CONTEXT_FIELDS = ("invoice_id", "user_id", "request_id", "step")

# Set while the pipeline works on an invoice, so every log line from that work (including
# from the agents and libraries) carries its invoice_id and step without passing `extra=`.
_context: ContextVar[dict | None] = ContextVar("log_context", default=None)


@contextmanager
def log_context(**fields: str) -> Iterator[None]:
    token = _context.set({**(_context.get() or {}), **fields})
    try:
        yield
    finally:
        _context.reset(token)


class JsonFormatter(logging.Formatter):
    """One JSON object per line, in the shape Cloud Logging parses natively."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = _context.get() or {}
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None) or context.get(field)
            if value is not None:
                entry[field] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

import json
import logging
import sys
from datetime import UTC, datetime

# Extra fields copied onto every JSON log line when passed via `extra=`.
_CONTEXT_FIELDS = ("invoice_id", "user_id", "request_id", "step")


class JsonFormatter(logging.Formatter):
    """One JSON object per line, in the shape Cloud Logging parses natively."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "severity": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in _CONTEXT_FIELDS:
            value = getattr(record, field, None)
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

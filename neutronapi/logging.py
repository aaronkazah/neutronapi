"""NeutronAPI logging infrastructure."""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Optional

from neutronapi.encoders import json_dumps_text


class EventFormatter(logging.Formatter):
    """Structured event formatter for machine-parseable output."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "event": getattr(record, "event", record.getMessage()),
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
        }

        for key in (
            "request_id",
            "method",
            "path",
            "status",
            "duration_ms",
            "ip",
            "user_agent",
            "user",
            "origin",
            "idempotency_key",
            "geo",
            "error",
            "retry_after",
            "limit",
            "remaining",
            "reset",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value

        message = record.getMessage()
        if payload["event"] != message:
            payload["message"] = message
        if record.exc_info and record.exc_info[1] is not None:
            payload["exc"] = self.formatException(record.exc_info)
        return json_dumps_text(payload)


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``neutronapi.*`` namespace."""
    if name.startswith("neutronapi."):
        return logging.getLogger(name)
    return logging.getLogger(f"neutronapi.{name}")


def log_event(logger: logging.Logger, level: int, event_name: str, **data) -> None:
    """Emit a structured event log."""
    logger.log(level, event_name, extra={"event": event_name, **data})


def configure_logging(
    level: str = "INFO",
    fmt: str = "text",
    stream: Optional[object] = None,
) -> None:
    """One-time setup for the ``neutronapi`` root logger."""
    root = logging.getLogger("neutronapi")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid adding duplicate handlers on repeated calls
    if root.handlers:
        return

    handler = logging.StreamHandler(stream or sys.stderr)
    if fmt == "json":
        handler.setFormatter(EventFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


def configure_from_settings() -> None:
    """Read LOGGING from settings and apply, if present."""
    try:
        from neutronapi.conf import settings

        cfg = settings.get("LOGGING", None)
        if cfg and isinstance(cfg, dict):
            configure_logging(
                level=cfg.get("level", "INFO"),
                fmt=cfg.get("format", "text"),
            )
    except Exception:
        pass

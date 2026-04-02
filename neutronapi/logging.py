"""NeutronAPI logging infrastructure.

Thin stdlib wrapper. Users route logs to external services by adding
their own handler to the ``neutronapi`` root logger::

    import logging
    logging.getLogger("neutronapi").addHandler(my_http_handler)

Framework modules obtain their logger via::

    from neutronapi.logging import get_logger
    logger = get_logger(__name__)
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Optional

from neutronapi.encoders import json_dumps_text


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for machine-parseable output.

    Produces one JSON object per line — suitable for shipping to
    Cloudflare Logpush, Datadog, or any log aggregation service.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1] is not None:
            payload["exc"] = self.formatException(record.exc_info)
        return json_dumps_text(payload)


def get_logger(name: str) -> logging.Logger:
    """Return a logger under the ``neutronapi.*`` namespace.

    If *name* already starts with ``neutronapi.`` it is used as-is;
    otherwise the prefix is added.
    """
    if name.startswith("neutronapi."):
        return logging.getLogger(name)
    return logging.getLogger(f"neutronapi.{name}")


def configure_logging(
    level: str = "INFO",
    fmt: str = "text",
    stream: Optional[object] = None,
) -> None:
    """One-time setup for the ``neutronapi`` root logger.

    Args:
        level: Log level name (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        fmt: ``"text"`` for human-readable or ``"json"`` for structured output.
        stream: Output stream (defaults to ``sys.stderr``).
    """
    root = logging.getLogger("neutronapi")
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid adding duplicate handlers on repeated calls
    if root.handlers:
        return

    handler = logging.StreamHandler(stream or sys.stderr)
    if fmt == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s")
        )
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

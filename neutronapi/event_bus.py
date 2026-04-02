"""Async event emitter for NeutronAPI."""

from __future__ import annotations

import asyncio
import dataclasses
import fnmatch
import inspect
import logging
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


_EVENT_LOGGER_MAP = {
    "request": "neutronapi.http",
    "websocket": "neutronapi.websocket",
    "app": "neutronapi.app",
    "scheduler": "neutronapi.scheduler",
    "task": "neutronapi.scheduler",
    "auth": "neutronapi.auth",
    "permission": "neutronapi.auth",
    "throttle": "neutronapi.auth",
    "db": "neutronapi.db",
    "migration": "neutronapi.migrations",
    "config": "neutronapi.config",
}


class _EventStream:
    def __init__(self, queue: asyncio.Queue, queue_list: list[asyncio.Queue]) -> None:
        self._queue = queue
        self._queue_list = queue_list
        self._closed = False

    def __aiter__(self) -> "_EventStream":
        return self

    async def __anext__(self) -> Any:
        if self._closed:
            raise StopAsyncIteration
        return await self._queue.get()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._queue in self._queue_list:
            self._queue_list.remove(self._queue)


class EventBus:
    """Async event emitter with callbacks, subscriptions, and logging bridge."""

    def __init__(self, *, queue_size: int = 1000) -> None:
        self.queue_size = queue_size
        self._handlers: dict[str, list[Callable[[Any], Any]]] = {}
        self._pattern_handlers: list[tuple[str, Callable[[Any], Any]]] = []
        self._channels: dict[str, list[asyncio.Queue]] = {}
        self._logger = logging.getLogger("neutronapi.events")

    def _logger_name(self, event_name: str) -> str:
        category = event_name.split(".", 1)[0]
        return _EVENT_LOGGER_MAP.get(category, f"neutronapi.{category}")

    def _should_bridge_to_logging(self, event_name: str) -> bool:
        logger = logging.getLogger(self._logger_name(event_name))
        return logger.isEnabledFor(logging.INFO) and logger.hasHandlers()

    async def _run_handler(self, handler: Callable[[Any], Any], event: Any) -> None:
        try:
            result = handler(event)
            if inspect.isawaitable(result):
                await result
        except Exception:
            self._logger.exception("Event handler failed for %s", getattr(event, "event", type(event).__name__))

    def _schedule_handler(self, handler: Callable[[Any], Any], event: Any) -> None:
        asyncio.create_task(self._run_handler(handler, event))

    def _push_to_queue(self, queue: asyncio.Queue, event: Any) -> None:
        if queue.full():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            return

    async def emit(self, event: Any) -> Any:
        """Emit a dataclass event."""
        if not dataclasses.is_dataclass(event):
            raise TypeError("EventBus.emit() expects a dataclass event instance.")

        if not getattr(event, "ts", ""):
            event = replace(event, ts=datetime.now(timezone.utc).isoformat())

        event_name = getattr(event, "event", "")
        log_enabled = self._should_bridge_to_logging(event_name)
        if not self._handlers and not self._pattern_handlers and not self._channels and not log_enabled:
            return event

        if handlers := self._handlers.get(event_name):
            for handler in list(handlers):
                self._schedule_handler(handler, event)

        for pattern, handler in list(self._pattern_handlers):
            if fnmatch.fnmatch(event_name, pattern):
                self._schedule_handler(handler, event)

        for pattern, queues in list(self._channels.items()):
            if not fnmatch.fnmatch(event_name, pattern):
                continue
            for queue in list(queues):
                self._push_to_queue(queue, event)

        if log_enabled:
            payload = dataclasses.asdict(event)
            logging.getLogger(self._logger_name(event_name)).info(
                event_name,
                extra={"event": event_name, **payload},
            )

        return event

    def on(self, event_pattern: str, handler: Callable[[Any], Any] | None = None):
        """Register a callback for an event name or glob pattern."""

        def decorator(fn: Callable[[Any], Any]) -> Callable[[Any], Any]:
            if "*" in event_pattern:
                self._pattern_handlers.append((event_pattern, fn))
            else:
                self._handlers.setdefault(event_pattern, []).append(fn)
            return fn

        if handler is not None:
            return decorator(handler)
        return decorator

    def subscribe(self, pattern: str = "*") -> _EventStream:
        """Create a bounded async stream for matching events."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=self.queue_size)
        queues = self._channels.setdefault(pattern, [])
        queues.append(queue)
        return _EventStream(queue, queues)

    def off(self, event_pattern: str, handler: Callable[[Any], Any]) -> None:
        """Unregister a callback."""
        if "*" in event_pattern:
            self._pattern_handlers = [
                (pattern, current)
                for pattern, current in self._pattern_handlers
                if not (pattern == event_pattern and current is handler)
            ]
            return

        handlers = self._handlers.get(event_pattern, [])
        self._handlers[event_pattern] = [current for current in handlers if current is not handler]
        if not self._handlers[event_pattern]:
            self._handlers.pop(event_pattern, None)


events = EventBus()


__all__ = ["EventBus", "events"]

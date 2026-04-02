"""Typed event catalog for NeutronAPI runtime events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Event:
    event: str = ""
    ts: str = ""


@dataclass(frozen=True)
class RequestEvent(Event):
    request_id: str = ""
    method: str = ""
    path: str = ""


@dataclass(frozen=True)
class RequestReceived(RequestEvent):
    event: str = "request.received"
    ip: str = ""
    user_agent: str = ""
    user: Optional[str] = None
    origin: Optional[str] = None
    idempotency_key: Optional[str] = None
    geo: Optional[str] = None


@dataclass(frozen=True)
class RequestCompleted(RequestEvent):
    event: str = "request.completed"
    status: int = 0
    duration_ms: float = 0.0
    ip: str = ""
    user_agent: str = ""
    user: Optional[str] = None
    origin: Optional[str] = None
    idempotency_key: Optional[str] = None
    geo: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class RequestError(RequestEvent):
    event: str = "request.error"
    status: int = 500
    error: str = ""
    ip: str = ""
    user_agent: str = ""
    user: Optional[str] = None
    origin: Optional[str] = None
    idempotency_key: Optional[str] = None
    geo: Optional[str] = None


@dataclass(frozen=True)
class WebSocketConnected(Event):
    event: str = "websocket.connected"
    path: str = ""
    client: str = ""


@dataclass(frozen=True)
class WebSocketRejected(Event):
    event: str = "websocket.rejected"
    path: str = ""
    code: int = 0
    reason: Optional[str] = None


@dataclass(frozen=True)
class AppStartup(Event):
    event: str = "app.startup"
    version: Optional[str] = None


@dataclass(frozen=True)
class AppStartupCompleted(Event):
    event: str = "app.startup.completed"
    version: Optional[str] = None


@dataclass(frozen=True)
class AppStartupFailed(Event):
    event: str = "app.startup.failed"
    error: str = ""


@dataclass(frozen=True)
class AppShutdown(Event):
    event: str = "app.shutdown"
    version: Optional[str] = None


@dataclass(frozen=True)
class AppShutdownCompleted(Event):
    event: str = "app.shutdown.completed"
    version: Optional[str] = None


@dataclass(frozen=True)
class SchedulerStarted(Event):
    event: str = "scheduler.started"
    poll_interval: float = 0.0


@dataclass(frozen=True)
class SchedulerStopped(Event):
    event: str = "scheduler.stopped"


@dataclass(frozen=True)
class TaskRegistered(Event):
    event: str = "task.registered"
    task_id: str = ""
    task_name: str = ""


@dataclass(frozen=True)
class TaskExecuting(Event):
    event: str = "task.executing"
    task_id: str = ""
    task_name: str = ""


@dataclass(frozen=True)
class TaskCompleted(Event):
    event: str = "task.completed"
    task_id: str = ""
    task_name: str = ""
    duration_ms: float = 0.0


@dataclass(frozen=True)
class TaskFailed(Event):
    event: str = "task.failed"
    task_id: str = ""
    task_name: str = ""
    error: str = ""


@dataclass(frozen=True)
class TaskDispatched(Event):
    event: str = "task.dispatched"
    task_id: str = ""
    task_name: str = ""


@dataclass(frozen=True)
class TaskEnabled(Event):
    event: str = "task.enabled"
    task_id: str = ""
    task_name: str = ""


@dataclass(frozen=True)
class TaskDisabled(Event):
    event: str = "task.disabled"
    task_id: str = ""
    task_name: str = ""


@dataclass(frozen=True)
class TaskRemoved(Event):
    event: str = "task.removed"
    task_id: str = ""
    task_name: str = ""


@dataclass(frozen=True)
class AuthSuccess(Event):
    event: str = "auth.success"
    request_id: str = ""
    user: Optional[str] = None


@dataclass(frozen=True)
class AuthFailed(Event):
    event: str = "auth.failed"
    request_id: str = ""
    error: str = ""


@dataclass(frozen=True)
class PermissionDenied(Event):
    event: str = "permission.denied"
    request_id: str = ""
    permission: Optional[str] = None


@dataclass(frozen=True)
class ThrottleLimited(Event):
    event: str = "throttle.limited"
    request_id: str = ""
    wait: Optional[int] = None


@dataclass(frozen=True)
class DBConnected(Event):
    event: str = "db.connected"
    alias: str = ""
    engine: str = ""


@dataclass(frozen=True)
class DBDisconnected(Event):
    event: str = "db.disconnected"
    alias: str = ""
    engine: str = ""


@dataclass(frozen=True)
class MigrationApplied(Event):
    event: str = "migration.applied"
    app_label: str = ""
    migration: str = ""


@dataclass(frozen=True)
class MigrationFailed(Event):
    event: str = "migration.failed"
    app_label: str = ""
    migration: str = ""
    error: str = ""


@dataclass(frozen=True)
class MigrationDrift(Event):
    event: str = "migration.drift"
    app_label: str = ""
    migration: str = ""
    reason: str = ""


@dataclass(frozen=True)
class ConfigLoaded(Event):
    event: str = "config.loaded"
    module: str = ""


@dataclass(frozen=True)
class ConfigFallback(Event):
    event: str = "config.fallback"
    module: str = ""
    reason: str = ""


ALL_EVENT_TYPES = (
    RequestReceived,
    RequestCompleted,
    RequestError,
    WebSocketConnected,
    WebSocketRejected,
    AppStartup,
    AppStartupCompleted,
    AppStartupFailed,
    AppShutdown,
    AppShutdownCompleted,
    SchedulerStarted,
    SchedulerStopped,
    TaskRegistered,
    TaskExecuting,
    TaskCompleted,
    TaskFailed,
    TaskDispatched,
    TaskEnabled,
    TaskDisabled,
    TaskRemoved,
    AuthSuccess,
    AuthFailed,
    PermissionDenied,
    ThrottleLimited,
    DBConnected,
    DBDisconnected,
    MigrationApplied,
    MigrationFailed,
    MigrationDrift,
    ConfigLoaded,
    ConfigFallback,
)


__all__ = [event_type.__name__ for event_type in ALL_EVENT_TYPES] + ["ALL_EVENT_TYPES", "Event"]

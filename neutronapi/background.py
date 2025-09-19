import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Dict, Any, Callable, Awaitable, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import traceback


__all__ = [
    'Background',
    'Task',
    'TaskFrequency',
    'TaskPriority',
    'TaskConfig',
    'TaskResult',
]


class TaskFrequency(Enum):
    ONCE = "once"
    MINUTELY = "minutely"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class TaskPriority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2


class Task:
    """Base class for background tasks - similar to API pattern."""

    name: str = ""
    frequency: TaskFrequency = TaskFrequency.ONCE
    priority: TaskPriority = TaskPriority.NORMAL
    interval: Optional[int] = None  # Custom interval in seconds

    async def run(self, **kwargs) -> Any:
        """Override this method to define your task logic."""
        raise NotImplementedError("Subclasses must implement the run method")


@dataclass
class TaskConfig:
    name: str
    frequency: TaskFrequency
    func: Callable[..., Awaitable[Any]]
    args: tuple = ()
    kwargs: Dict[str, Any] = None
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    interval: Optional[int] = None  # Interval in seconds for custom frequencies
    enabled: bool = True
    priority: TaskPriority = TaskPriority.NORMAL
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class TaskResult:
    task_id: str
    success: bool
    result: Any = None
    error: Optional[Exception] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def duration(self) -> Optional[float]:
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None


class Background:
    """Manages periodic task execution and async task queues."""

    def __init__(self) -> None:
        """Initialize background task scheduler."""
        self.tasks: Dict[str, TaskConfig] = {}
        self.running = False
        self._task: Optional[asyncio.Task] = None
        self.logger = logging.getLogger("TaskScheduler")

        # Queues for different priority levels
        self._queues: Dict[TaskPriority, asyncio.Queue] = {
            TaskPriority.LOW: asyncio.Queue(),
            TaskPriority.NORMAL: asyncio.Queue(),
            TaskPriority.HIGH: asyncio.Queue(),
        }

        # Task results storage
        self._results: Dict[str, TaskResult] = {}

    def register_task(self, task: Task) -> str:
        """Register a Task class instance - mirrors API pattern."""
        name = task.name or task.__class__.__name__
        return self.add_task(
            name=name,
            func=task.run,
            frequency=task.frequency,
            interval=task.interval,
            priority=task.priority,
        )

    def add_task(
        self,
        name: str,
        func: Callable[..., Awaitable[Any]],
        frequency: TaskFrequency,
        interval: Optional[int] = None,
        args: tuple = (),
        kwargs: Dict[str, Any] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> str:
        """Add a new task to the scheduler."""
        if kwargs is None:
            kwargs = {}

        task_config = TaskConfig(
            name=name,
            frequency=frequency,
            func=func,
            args=args,
            kwargs=kwargs,
            interval=interval,
            last_run=None,
            next_run=self._calculate_next_run(frequency, interval),
            priority=priority,
        )
        self.tasks[task_config.task_id] = task_config
        self.logger.info(f"Added task: {name} with frequency {frequency}")
        return task_config.task_id

    async def run_task_async(
        self,
        func: Callable[..., Awaitable[Any]],
        *args,
        priority: TaskPriority = TaskPriority.NORMAL,  # Priority argument will be ignored for now
        **kwargs,
    ) -> str:
        """
        Run a one-time task asynchronously.
        Returns a task_id that can be used to check the result later.
        MODIFIED: This now dispatches the task for immediate execution, bypassing queues.
        """
        task_id = str(uuid.uuid4())
        task_config = TaskConfig(
            name=f"async_task_{task_id}",
            frequency=TaskFrequency.ONCE,
            func=func,
            args=args,
            kwargs=kwargs,
            priority=priority,  # Stored in config, but not used for queuing in this modified version
            task_id=task_id,
        )
        # Directly create an asyncio task for _execute_task.
        # This makes it run concurrently without waiting for a queue worker.
        asyncio.create_task(self._execute_task(task_config))

        self.logger.info(
            f"Immediately dispatched async task {task_id} ({task_config.name}) for concurrent execution."
        )

        return task_id

    async def get_task_result(
        self, task_id: str, wait: bool = False
    ) -> Optional[TaskResult]:
        """
        Get the result of a task by its ID.
        If wait is True, will wait until the task completes.
        """
        if wait:
            while task_id not in self._results:
                await asyncio.sleep(0.1)
        return self._results.get(task_id)

    def remove_task(self, task_id: str) -> None:
        """Remove a task from the scheduler.
        
        Args:
            task_id: ID of the task to remove
        """
        if task_id in self.tasks:
            task_name = self.tasks[task_id].name
            del self.tasks[task_id]
            self.logger.info(f"Removed task: {task_name}")

    def _calculate_next_run(
        self, frequency: TaskFrequency, interval: Optional[int] = None
    ) -> datetime:
        """Calculate the next run time for a task based on its frequency."""
        now = datetime.now()

        if frequency == TaskFrequency.ONCE:
            return now

        if interval is not None:
            return now + timedelta(seconds=interval)

        if frequency == TaskFrequency.MINUTELY:
            next_run = now.replace(second=0) + timedelta(minutes=1)
        elif frequency == TaskFrequency.HOURLY:
            next_run = now.replace(minute=0, second=0) + timedelta(hours=1)
        elif frequency == TaskFrequency.DAILY:
            next_run = now.replace(hour=0, minute=0, second=0) + timedelta(days=1)
        elif frequency == TaskFrequency.WEEKLY:
            next_run = now.replace(hour=0, minute=0, second=0)
            days_ahead = 7 - next_run.weekday()
            next_run += timedelta(days=days_ahead)
        elif frequency == TaskFrequency.MONTHLY:
            if now.month == 12:
                next_run = now.replace(
                    year=now.year + 1, month=1, day=1, hour=0, minute=0, second=0
                )
            else:
                next_run = now.replace(
                    month=now.month + 1, day=1, hour=0, minute=0, second=0
                )
        else:
            next_run = now

        return next_run

    async def _execute_task(self, task: TaskConfig) -> TaskResult:
        """Execute a single task and update its schedule."""

        result = TaskResult(
            task_id=task.task_id, success=False, start_time=datetime.now()
        )

        try:
            self.logger.info(f"Executing task: {task.name}")
            actual_result = await task.func(*task.args, **(task.kwargs or {}))
            result.result = actual_result
            result.success = True

            if task.frequency != TaskFrequency.ONCE:
                task.last_run = datetime.now()
                task.next_run = self._calculate_next_run(task.frequency, task.interval)
                self.logger.info(
                    f"Task {task.name} completed. Next run at {task.next_run}"
                )
            else:
                self.logger.info(f"Task {task.name} was one-time only, not rescheduled")

        except Exception as e:
            self.logger.error(
                f"Error executing task {task.name}: {str(e)}", exc_info=True
            )
            result.error = e
            # Print stack trace in logs but not to console
            self.logger.error(traceback.format_exc())

        result.end_time = datetime.now()
        self._results[task.task_id] = result

        return result

    async def _process_queue(self, priority: TaskPriority) -> None:
        """Process tasks from a specific priority queue."""
        while self.running:
            try:

                task = await self._queues[priority].get()

                await self._execute_task(task)
                self._queues[priority].task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:

                self.logger.error(f"Error in queue processor: {str(e)}", exc_info=True)
                await asyncio.sleep(1)

    async def _scheduler_loop(self) -> None:
        """Main scheduler loop that checks and executes due tasks."""
        # Start queue processors
        queue_processors = []
        for priority in TaskPriority:
            processor = asyncio.create_task(self._process_queue(priority))
            queue_processors.append(processor)

        self.logger.info(f"Scheduler started with {len(self.tasks)} registered tasks")

        # Log all registered tasks
        for task in self.tasks.values():
            task_info = f"Task registered: {task.name}, frequency: {task.frequency}, next run: {task.next_run}"
            self.logger.info(task_info)

        # Log startup confirmation
        self.logger.info(
            f"Scheduler main loop is now running. Running state: {self.running}"
        )

        try:
            while self.running:
                now = datetime.now()

                # Find tasks that need to be run
                due_tasks = [
                    task
                    for task in self.tasks.values()
                    if task.enabled and task.next_run and task.next_run <= now
                ]

                # Execute due tasks
                if due_tasks:
                    due_msg = f"Found {len(due_tasks)} tasks due for execution at {now}"
                    self.logger.info(due_msg)

                    for task in due_tasks:
                        task_msg = f"Executing task: {task.name}, last_run: {task.last_run}, frequency: {task.frequency}"
                        self.logger.info(task_msg)

                    # Sort by priority
                    due_tasks.sort(key=lambda x: x.priority.value, reverse=True)

                    await asyncio.gather(
                        *(self._execute_task(task) for task in due_tasks)
                    )
                else:
                    # Log status every minute to show the scheduler is alive
                    if now.second == 0:
                        alive_msg = f"Scheduler alive at {now}, waiting for tasks... ({len(self.tasks)} registered)"
                        self.logger.info(alive_msg)

                # Sleep for a short interval before next check
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            self.logger.info("Scheduler loop cancelled")
        finally:

            # Cancel queue processors
            for processor in queue_processors:
                processor.cancel()
            await asyncio.gather(*queue_processors, return_exceptions=True)
            self.logger.info("Scheduler loop shutdown complete")

    async def start(self) -> None:
        """Start the task scheduler."""
        self.logger.info(
            f"TaskScheduler.start() called - current running state: {self.running}"
        )
        if not self.running:
            self.running = True
            self.logger.info(
                f"Creating scheduler loop task, running state set to: {self.running}"
            )

            self._task = asyncio.create_task(self._scheduler_loop())
            self.logger.info("Task scheduler started")

    async def stop(self) -> None:
        """Stop the task scheduler."""
        if self.running:
            self.running = False
            if self._task:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:

                    pass
            self._task = None
            self.logger.info("Task scheduler stopped")

    def get_task(self, task_id: str) -> Optional[TaskConfig]:
        """Get task configuration by ID."""
        return self.tasks.get(task_id)

    def get_all_tasks(self) -> List[TaskConfig]:
        """Get all registered tasks."""
        return list(self.tasks.values())

    def enable_task(self, task_id: str) -> None:
        """Enable a task by ID."""
        if task := self.tasks.get(task_id):
            task.enabled = True
            task.next_run = self._calculate_next_run(task.frequency, task.interval)
            self.logger.info(f"Enabled task: {task.name}")

    def disable_task(self, task_id: str) -> None:
        """Disable a task by ID."""
        if task := self.tasks.get(task_id):
            task.enabled = False
            self.logger.info(f"Disabled task: {task.name}")

    def clear_task_result(self, task_id: str) -> None:
        """Clear the stored result for a task."""
        if task_id in self._results:
            del self._results[task_id]


# No global instance by design; applications should pass a Background

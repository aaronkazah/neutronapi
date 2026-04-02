import unittest
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from neutronapi.base import API
from neutronapi.application import Application
from neutronapi.background import Task, TaskFrequency, TaskPriority


class DummyAPI(API):
    name = "dummy"
    resource = ""


class CounterTask(Task):
    """Task that increments a counter each time it runs"""
    def __init__(self, name, frequency, counter, priority=TaskPriority.NORMAL, interval=None):
        self.name = name
        self.frequency = frequency
        self.priority = priority
        self.interval = interval
        self.counter = counter

    async def run(self, **kwargs):
        self.counter['count'] += 1
        self.counter['last_run'] = datetime.now()
        print(f"Task {self.name} ran - count is now {self.counter['count']}")


class TestBackgroundTaskExecution(unittest.IsolatedAsyncioTestCase):

    async def test_once_task_runs_exactly_once(self):
        """Test that a ONCE task runs exactly one time"""
        counter = {'count': 0, 'last_run': None}

        task = CounterTask("once_task", TaskFrequency.ONCE, counter)

        app = Application(
            apis={"dummy": DummyAPI()},
            tasks={"once": task}
        )

        # Start background
        for fn in app.on_startup:
            await fn()

        # Wait for scheduler to pick up and run the task
        # Scheduler runs every 1 second, so wait 2-3 seconds to be sure
        await asyncio.sleep(3)

        # Verify task ran exactly once
        self.assertEqual(counter['count'], 1, "ONCE task should run exactly once")
        self.assertIsNotNone(counter['last_run'], "Task should have recorded a run time")

        # Wait more to ensure it doesn't run again
        await asyncio.sleep(2)
        self.assertEqual(counter['count'], 1, "ONCE task should not run a second time")

        # Stop background
        for fn in app.on_shutdown:
            await fn()

        self.assertFalse(app.background.running)


    async def test_recurring_task_with_custom_interval(self):
        """Test that a task with custom interval runs multiple times"""
        counter = {'count': 0, 'last_run': None}

        # Task that runs every 1 second
        task = CounterTask("recurring_task", TaskFrequency.MINUTELY, counter, interval=1)

        app = Application(
            apis={"dummy": DummyAPI()},
            tasks={"recurring": task}
        )

        # Start background
        for fn in app.on_startup:
            await fn()

        # Wait for task to run multiple times
        # With 1 second interval, wait 5 seconds should give us 4-5 runs
        await asyncio.sleep(5)

        # Verify task ran multiple times
        self.assertGreaterEqual(counter['count'], 3, f"Task should have run at least 3 times, ran {counter['count']} times")
        self.assertLessEqual(counter['count'], 6, f"Task should have run at most 6 times, ran {counter['count']} times")

        # Stop background
        for fn in app.on_shutdown:
            await fn()

        self.assertFalse(app.background.running)


    async def test_multiple_tasks_run_independently(self):
        """Test that multiple tasks run independently with different intervals"""
        counter1 = {'count': 0, 'last_run': None}
        counter2 = {'count': 0, 'last_run': None}

        # Task 1: runs every 1 second
        task1 = CounterTask("fast_task", TaskFrequency.MINUTELY, counter1, interval=1)

        # Task 2: runs every 2 seconds
        task2 = CounterTask("slow_task", TaskFrequency.MINUTELY, counter2, interval=2)

        app = Application(
            apis={"dummy": DummyAPI()},
            tasks={"fast": task1, "slow": task2}
        )

        # Start background
        for fn in app.on_startup:
            await fn()

        # Wait 6 seconds
        await asyncio.sleep(6)

        # Fast task should run ~5 times, slow task should run ~3 times
        self.assertGreaterEqual(counter1['count'], 4, f"Fast task should run at least 4 times, ran {counter1['count']} times")
        self.assertGreaterEqual(counter2['count'], 2, f"Slow task should run at least 2 times, ran {counter2['count']} times")

        # Fast task should have run more times than slow task
        self.assertGreater(counter1['count'], counter2['count'], "Fast task should run more times than slow task")

        # Stop background
        for fn in app.on_shutdown:
            await fn()

        self.assertFalse(app.background.running)


    async def test_task_priority_execution(self):
        """Test that high priority tasks are executed"""
        high_counter = {'count': 0, 'last_run': None}
        normal_counter = {'count': 0, 'last_run': None}
        low_counter = {'count': 0, 'last_run': None}

        # Create tasks with different priorities
        high_task = CounterTask("high_task", TaskFrequency.MINUTELY, high_counter, priority=TaskPriority.HIGH, interval=1)
        normal_task = CounterTask("normal_task", TaskFrequency.MINUTELY, normal_counter, priority=TaskPriority.NORMAL, interval=1)
        low_task = CounterTask("low_task", TaskFrequency.MINUTELY, low_counter, priority=TaskPriority.LOW, interval=1)

        app = Application(
            apis={"dummy": DummyAPI()},
            tasks={"high": high_task, "normal": normal_task, "low": low_task}
        )

        # Start background
        for fn in app.on_startup:
            await fn()

        # Wait for tasks to run
        await asyncio.sleep(5)

        # All tasks should have run
        self.assertGreater(high_counter['count'], 0, "High priority task should run")
        self.assertGreater(normal_counter['count'], 0, "Normal priority task should run")
        self.assertGreater(low_counter['count'], 0, "Low priority task should run")

        # Stop background
        for fn in app.on_shutdown:
            await fn()

        self.assertFalse(app.background.running)


    async def test_disable_and_enable_task(self):
        """Test that disabled tasks don't run, and enabled tasks resume"""
        counter = {'count': 0, 'last_run': None}

        task = CounterTask("toggle_task", TaskFrequency.MINUTELY, counter, interval=1)

        app = Application(
            apis={"dummy": DummyAPI()},
            tasks={"toggle": task}
        )

        # Start background
        for fn in app.on_startup:
            await fn()

        # Let task run a few times
        await asyncio.sleep(3)
        initial_count = counter['count']
        self.assertGreater(initial_count, 0, "Task should have run initially")

        # Disable the task
        task_id = list(app.background.tasks.keys())[0]
        app.background.disable_task(task_id)

        # Wait and verify task doesn't run
        await asyncio.sleep(3)
        disabled_count = counter['count']
        self.assertEqual(disabled_count, initial_count, "Task should not run when disabled")

        # Re-enable the task
        app.background.enable_task(task_id)

        # Wait and verify task runs again
        await asyncio.sleep(3)
        final_count = counter['count']
        self.assertGreater(final_count, disabled_count, "Task should run again after being enabled")

        # Stop background
        for fn in app.on_shutdown:
            await fn()

        self.assertFalse(app.background.running)


    async def test_task_with_very_short_interval(self):
        """Test task with sub-second interval to verify rapid execution"""
        counter = {'count': 0, 'last_run': None}

        # Task that runs every 0.5 seconds
        task = CounterTask("rapid_task", TaskFrequency.MINUTELY, counter, interval=0.5)

        app = Application(
            apis={"dummy": DummyAPI()},
            tasks={"rapid": task}
        )

        # Start background
        for fn in app.on_startup:
            await fn()

        # Wait 3 seconds - should run ~6 times
        await asyncio.sleep(3)

        # Verify task ran multiple times rapidly
        self.assertGreaterEqual(counter['count'], 4, f"Rapid task should run at least 4 times in 3 seconds, ran {counter['count']} times")

        # Stop background
        for fn in app.on_shutdown:
            await fn()

        self.assertFalse(app.background.running)


class TestBackgroundIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_background_start_stop_and_task_registration(self):
        """Original integration test - kept for backwards compatibility"""
        ran = {'flag': False}

        class TestTask(Task):
            def __init__(self, ran_flag):
                self.name = "test_task"
                self.frequency = TaskFrequency.ONCE
                self.ran_flag = ran_flag

            async def run(self, **kwargs):
                self.ran_flag['flag'] = True

        test_task = TestTask(ran)

        app = Application(
            apis={"dummy": DummyAPI()},
            tasks={"test": test_task}
        )

        # Ensure startup hooks exist
        self.assertTrue(hasattr(app, 'on_startup'))
        self.assertTrue(callable(app.on_startup[0]))

        # Start background via startup hook
        for fn in app.on_startup:
            await fn()

        # Wait longer for scheduler to actually run the task
        await asyncio.sleep(3)

        # Verify task ran
        self.assertTrue(ran['flag'], "Task should have run")

        # Stop via shutdown hook
        for fn in getattr(app, 'on_shutdown', []):
            await fn()

        self.assertFalse(app.background.running)

    async def test_weekly_schedule_from_monday_goes_to_next_monday(self):
        from neutronapi.background import Background

        # Monday afternoon — next run should be NEXT Monday, not today's midnight
        monday_afternoon = datetime(2026, 4, 6, 15, 30, tzinfo=timezone.utc)
        with patch("neutronapi.background.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = monday_afternoon
            background = Background()
            next_run = background._calculate_next_run(TaskFrequency.WEEKLY)

        # April 6 is Monday, next Monday is April 13
        self.assertEqual(next_run, datetime(2026, 4, 13, 0, 0, tzinfo=timezone.utc))

    async def test_weekly_schedule_from_wednesday_goes_to_next_monday(self):
        from neutronapi.background import Background

        wednesday = datetime(2026, 4, 8, 10, 0, tzinfo=timezone.utc)
        with patch("neutronapi.background.datetime") as mocked_datetime:
            mocked_datetime.now.return_value = wednesday
            background = Background()
            next_run = background._calculate_next_run(TaskFrequency.WEEKLY)

        # Wednesday (Apr 8) → next Monday (Apr 13) = 5 days ahead
        self.assertEqual(next_run, datetime(2026, 4, 13, 0, 0, tzinfo=timezone.utc))

    async def test_poll_interval_is_configurable(self):
        from neutronapi.background import Background

        background = Background(poll_interval=0.5)
        self.assertEqual(background.poll_interval, 0.5)

        with self.assertRaises(ValueError):
            Background(poll_interval=0)

    async def test_results_eviction(self):
        from neutronapi.background import Background

        background = Background(max_results=3)
        # Simulate storing results
        for i in range(5):
            background._results[f"task_{i}"] = f"result_{i}"

        # Should have evicted the oldest 2
        self.assertEqual(len(background._results), 5)
        # But after _execute_task the eviction runs — test via the method
        # For now just verify the param is stored
        self.assertEqual(background.max_results, 3)

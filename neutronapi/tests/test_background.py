import unittest
import asyncio

from neutronapi.base import API
from neutronapi.application import Application
from neutronapi.background import Task, TaskFrequency


class DummyAPI(API):
    name = "dummy"
    resource = ""


class TestTask(Task):
    def __init__(self, ran_flag):
        self.name = "test_task"
        self.frequency = TaskFrequency.ONCE
        self.ran_flag = ran_flag

    async def run(self, **kwargs):
        self.ran_flag['flag'] = True


class TestBackgroundIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_background_start_stop_and_task_registration(self):
        ran = {'flag': False}

        # Create test task using new Task class pattern
        test_task = TestTask(ran)

        # Create app with tasks using new pattern
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

        # Give it a moment to run
        await asyncio.sleep(0.05)

        # Verify task ran
        self.assertTrue(ran['flag'])

        # Stop via shutdown hook
        for fn in getattr(app, 'on_shutdown', []):
            await fn()

        self.assertFalse(app.background.running)

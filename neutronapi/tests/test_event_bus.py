import asyncio
import dataclasses
import logging
import unittest
from io import StringIO

from neutronapi.event_bus import EventBus
from neutronapi.events import ALL_EVENT_TYPES, RequestCompleted, RequestReceived
from neutronapi.logging import configure_logging


class TestEventBus(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        root = logging.getLogger("neutronapi")
        root.handlers.clear()

    def tearDown(self):
        root = logging.getLogger("neutronapi")
        root.handlers.clear()

    async def test_emit_calls_registered_callback(self):
        bus = EventBus()
        seen = []
        done = asyncio.Event()

        @bus.on("request.completed")
        async def handler(event):
            seen.append(event.request_id)
            done.set()

        await bus.emit(RequestCompleted(request_id="req_1", method="GET", path="/"))
        await asyncio.wait_for(done.wait(), timeout=1)
        self.assertEqual(seen, ["req_1"])

    async def test_pattern_handler_receives_matching_events(self):
        bus = EventBus()
        seen = []
        done = asyncio.Event()

        @bus.on("request.*")
        async def handler(event):
            seen.append(event.event)
            done.set()

        await bus.emit(RequestReceived(request_id="req_1", method="GET", path="/"))
        await asyncio.wait_for(done.wait(), timeout=1)
        self.assertEqual(seen, ["request.received"])

    async def test_subscribe_stream_receives_events(self):
        bus = EventBus()
        stream = bus.subscribe("request.*")
        try:
            await bus.emit(RequestCompleted(request_id="req_2", method="GET", path="/test"))
            event = await asyncio.wait_for(stream.__anext__(), timeout=1)
            self.assertEqual(event.request_id, "req_2")
        finally:
            await stream.close()

    async def test_logging_bridge_writes_structured_event(self):
        buf = StringIO()
        configure_logging(level="INFO", fmt="json", stream=buf)
        bus = EventBus()
        await bus.emit(RequestCompleted(request_id="req_3", method="GET", path="/logged", status=200))
        output = buf.getvalue()
        self.assertIn('"request.completed"', output)
        self.assertIn('"req_3"', output)

    async def test_off_unregisters_handler(self):
        bus = EventBus()
        seen = []

        async def handler(event):
            seen.append(event.request_id)

        bus.on("request.completed", handler)
        bus.off("request.completed", handler)
        await bus.emit(RequestCompleted(request_id="req_4", method="GET", path="/"))
        await asyncio.sleep(0)
        self.assertEqual(seen, [])

    async def test_all_event_types_are_serializable(self):
        for event_type in ALL_EVENT_TYPES:
            payload = dataclasses.asdict(event_type())
            self.assertIn("event", payload)
            self.assertIn("ts", payload)

    async def test_emit_without_subscribers_keeps_bus_stateless(self):
        bus = EventBus()
        for index in range(100):
            await bus.emit(RequestCompleted(request_id=f"req_{index}", method="GET", path="/"))
        self.assertEqual(bus._handlers, {})
        self.assertEqual(bus._pattern_handlers, [])
        self.assertEqual(bus._channels, {})

    async def test_bounded_queue_drops_oldest(self):
        bus = EventBus(queue_size=3)
        stream = bus.subscribe("request.*")
        try:
            for index in range(5):
                await bus.emit(RequestCompleted(request_id=f"req_{index}", method="GET", path="/"))
            seen = [await asyncio.wait_for(stream.__anext__(), timeout=1) for _ in range(3)]
            self.assertEqual([event.request_id for event in seen], ["req_2", "req_3", "req_4"])
        finally:
            await stream.close()

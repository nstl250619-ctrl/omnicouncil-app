"""Unit tests for shared/event_bus.py."""

from __future__ import annotations

import asyncio


from shared.event_bus import EventBus


class TestEventBus:
    def setup_method(self):
        EventBus.reset()

    def teardown_method(self):
        EventBus.reset()

    def test_singleton(self):
        bus1 = EventBus()
        bus2 = EventBus()
        assert bus1 is bus2

    def test_register_and_emit(self):
        bus = EventBus()
        received = []

        def handler(**kwargs):
            received.append(kwargs)

        bus.on("test", handler)
        asyncio.run(bus.emit("test", key="value"))
        assert len(received) == 1
        assert received[0]["key"] == "value"

    def test_multiple_handlers(self):
        bus = EventBus()
        count = [0, 0]

        def h1(**kw):
            count[0] += 1

        def h2(**kw):
            count[1] += 1

        bus.on("test", h1)
        bus.on("test", h2)
        asyncio.run(bus.emit("test"))
        assert count == [1, 1]

    def test_off_removes_handler(self):
        bus = EventBus()
        count = [0]

        def handler(**kw):
            count[0] += 1

        bus.on("test", handler)
        bus.off("test", handler)
        asyncio.run(bus.emit("test"))
        assert count[0] == 0

    def test_off_nonexistent_handler_no_error(self):
        bus = EventBus()

        def handler(**kw):
            pass

        bus.off("test", handler)  # Should not raise

    def test_emit_no_handlers(self):
        bus = EventBus()
        asyncio.run(bus.emit("nonexistent"))  # Should not raise

    def test_handler_exception_does_not_propagate(self):
        bus = EventBus()
        count = [0]

        def bad_handler(**kw):
            raise RuntimeError("boom")

        def good_handler(**kw):
            count[0] += 1

        bus.on("test", bad_handler)
        bus.on("test", good_handler)
        asyncio.run(bus.emit("test"))
        assert count[0] == 1  # good handler still runs

    def test_async_handler(self):
        bus = EventBus()
        received = []

        async def handler(**kwargs):
            received.append(kwargs)

        bus.on("test", handler)
        asyncio.run(bus.emit("test", data=42))
        assert len(received) == 1

    def test_registered_events(self):
        bus = EventBus()
        bus.on("a", lambda **k: None)
        bus.on("b", lambda **k: None)
        events = bus.registered_events
        assert "a" in events
        assert "b" in events

    def test_reset_clears_handlers(self):
        bus = EventBus()
        bus.on("test", lambda **k: None)
        EventBus.reset()
        bus2 = EventBus()
        assert len(bus2._handlers) == 0

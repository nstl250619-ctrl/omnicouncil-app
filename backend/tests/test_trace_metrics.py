"""Unit tests for shared/trace.py, shared/metrics.py, shared/replay.py, shared/instrumentation.py."""

from __future__ import annotations

import time


from shared.trace import Trace, TraceStore
from shared.metrics import MetricsCollector
from shared.replay import ReplayEngine
from shared.instrumentation import Instrumentation
from shared.event_bus import EventBus


class TestTrace:
    def test_create_trace(self):
        t = Trace(trace_id="tr1", task_id="t1", started_at=time.time())
        assert t.trace_id == "tr1"
        assert t.task_id == "t1"
        assert t.status == "running"

    def test_record_event(self):
        t = Trace(trace_id="tr1", task_id="t1", started_at=time.time())
        t.record("scheduler", "task_created", {"key": "value"})
        assert len(t.events) == 1
        assert t.events[0].layer == "scheduler"
        assert t.events[0].event == "task_created"
        assert t.events[0].data["key"] == "value"

    def test_complete(self):
        t = Trace(trace_id="tr1", task_id="t1", started_at=time.time())
        t.complete("completed")
        assert t.status == "completed"
        assert t.finished_at > 0


class TestTraceStore:
    def setup_method(self):
        TraceStore.reset()

    def teardown_method(self):
        TraceStore.reset()

    def test_singleton(self):
        s1 = TraceStore.instance()
        s2 = TraceStore.instance()
        assert s1 is s2

    def test_create_and_get(self):
        store = TraceStore.instance()
        trace = store.create("t1", query="test", ai_ids=["ai1"])
        assert trace.task_id == "t1"
        assert store.get("t1") is trace

    def test_get_by_trace_id(self):
        store = TraceStore.instance()
        trace = store.create("t1")
        found = store.get_by_trace_id(trace.trace_id)
        assert found is trace

    def test_get_nonexistent(self):
        store = TraceStore.instance()
        assert store.get("nonexistent") is None

    def test_fifo_eviction(self):
        store = TraceStore.instance()
        for i in range(105):
            store.create(f"t{i}")
        assert len(store.all()) <= 100

    def test_all(self):
        store = TraceStore.instance()
        store.create("t1")
        store.create("t2")
        assert len(store.all()) == 2

    def test_reset(self):
        store = TraceStore.instance()
        store.create("t1")
        TraceStore.reset()
        store2 = TraceStore.instance()
        assert len(store2.all()) == 0


class TestMetricsCollector:
    def setup_method(self):
        MetricsCollector.reset()

    def teardown_method(self):
        MetricsCollector.reset()

    def test_singleton(self):
        m1 = MetricsCollector.instance()
        m2 = MetricsCollector.instance()
        assert m1 is m2

    def test_inc(self):
        m = MetricsCollector.instance()
        m.inc("requests")
        m.inc("requests", 5)
        assert m._counters["requests"] == 6

    def test_inc_provider(self):
        m = MetricsCollector.instance()
        m.inc_provider("deepseek", "success")
        assert m._per_provider["deepseek"]["success"] == 1

    def test_record_latency(self):
        m = MetricsCollector.instance()
        m.record_latency("test", 100.0)
        m.record_latency("test", 200.0)
        assert len(m._latency["test"]) == 2

    def test_record_provider_latency(self):
        m = MetricsCollector.instance()
        m.record_provider_latency("deepseek", 500.0)
        assert len(m._per_provider_latency["deepseek"]) == 1

    def test_latency_buffer_limit(self):
        m = MetricsCollector.instance()
        for i in range(1100):
            m.record_latency("test", float(i))
        assert len(m._latency["test"]) == 1000

    def test_snapshot(self):
        m = MetricsCollector.instance()
        m.inc("requests", 10)
        m.inc("success", 8)
        snap = m.snapshot()
        assert snap["counters"]["requests"] == 10
        assert snap["counters"]["success"] == 8
        assert "uptime_seconds" in snap

    def test_snapshot_percentiles(self):
        m = MetricsCollector.instance()
        for i in range(100):
            m.record_latency("test", float(i))
        snap = m.snapshot()
        lat = snap["latency"]["test"]
        assert lat["count"] == 100
        assert lat["p50"] > 0
        assert lat["p95"] > 0

    def test_snapshot_empty(self):
        m = MetricsCollector.instance()
        snap = m.snapshot()
        assert snap["counters"] == {}

    def test_percentiles_empty(self):
        result = MetricsCollector._percentiles([])
        assert result["count"] == 0
        assert result["avg"] == 0

    def test_reset_all(self):
        m = MetricsCollector.instance()
        m.inc("test", 100)
        m.reset_all()
        assert m._counters == {}


class TestReplayEngine:
    def test_replay_nonexistent(self):
        TraceStore.reset()
        engine = ReplayEngine()
        result = engine.replay("nonexistent")
        assert result is None

    def test_replay_trace(self):
        TraceStore.reset()
        store = TraceStore.instance()
        trace = store.create("t1", query="test query")
        trace.record("scheduler", "task_created")
        trace.record("provider", "send_prompt_end", {
            "ai_id": "deepseek",
            "success": True,
            "raw_text": "hello response",
            "duration": 1.0,
        })
        trace.record("collector", "context_ready")

        engine = ReplayEngine(store)
        result = engine.replay("t1")

        assert result is not None
        assert result.task_id == "t1"
        assert result.query == "test query"
        assert len(result.steps) == 3

    def test_replay_by_trace_id(self):
        TraceStore.reset()
        store = TraceStore.instance()
        trace = store.create("t1")
        trace.record("scheduler", "task_created")

        engine = ReplayEngine(store)
        result = engine.replay_by_trace_id(trace.trace_id)
        assert result is not None

    def test_replay_normalizes_response(self):
        TraceStore.reset()
        store = TraceStore.instance()
        trace = store.create("t1")
        trace.record("provider", "send_prompt_end", {
            "ai_id": "deepseek",
            "success": True,
            "raw_text": "量子计算是新型计算方式",
        })

        engine = ReplayEngine(store)
        result = engine.replay("t1")

        assert "deepseek" in result.reconstructed_results
        assert result.steps[0].replay_result.get("word_count", 0) > 0


class TestInstrumentation:
    def setup_method(self):
        EventBus.reset()
        TraceStore.reset()
        MetricsCollector.reset()

    def teardown_method(self):
        EventBus.reset()
        TraceStore.reset()
        MetricsCollector.reset()

    def test_disabled_install(self):
        bus = EventBus()
        inst = Instrumentation(bus, tracing_enabled=False, metrics_enabled=False)
        inst.install()  # Should not raise
        # No handlers registered
        assert len(bus._handlers) == 0

    def test_enabled_install(self):
        bus = EventBus()
        inst = Instrumentation(bus, tracing_enabled=True, metrics_enabled=True)
        inst.install()
        # Should have handlers
        assert len(bus._handlers) > 0

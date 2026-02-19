"""Unit tests for observability hooks."""

import time

from sentient_ledger.observability import NodeEvent, PipelineObserver, wrap_node


def _dummy_node(state: dict) -> dict:
    return {"output_key": "value"}


def _slow_node(state: dict) -> dict:
    time.sleep(0.01)
    return {"slow_output": True}


class TestNodeEvent:
    def test_node_event_creation(self):
        event = NodeEvent(
            node_name="test_node",
            trace_id="trace-1",
            started_at=100.0,
            ended_at=100.5,
            duration_ms=500.0,
            state_keys_in=["trace_id", "data"],
            state_keys_out=["result"],
        )
        assert event.node_name == "test_node"
        assert event.duration_ms == 500.0
        assert event.trace_id == "trace-1"


class TestPipelineObserver:
    def test_observer_records_events(self):
        observer = PipelineObserver()
        state = {"trace_id": "t1", "data": [1, 2]}
        observer.on_node_enter("nodeA", state)
        observer.on_node_exit("nodeA", state, {"out": True})
        assert len(observer.events) == 1
        assert observer.events[0].node_name == "nodeA"
        assert observer.events[0].trace_id == "t1"
        assert observer.events[0].duration_ms >= 0

    def test_observer_summary_total_duration(self):
        observer = PipelineObserver()
        state = {"trace_id": "t1"}
        observer.on_node_enter("a", state)
        observer.on_node_exit("a", state, {"x": 1})
        observer.on_node_enter("b", state)
        observer.on_node_exit("b", state, {"y": 2})
        summary = observer.summary()
        assert summary["node_count"] == 2
        assert summary["total_duration_ms"] >= 0

    def test_observer_summary_per_node(self):
        observer = PipelineObserver()
        state = {"trace_id": "t1"}
        observer.on_node_enter("fast", state)
        observer.on_node_exit("fast", state, {"r": 1})
        summary = observer.summary()
        assert "fast" in summary["nodes"]
        assert "duration_ms" in summary["nodes"]["fast"]

    def test_observer_empty_summary(self):
        observer = PipelineObserver()
        summary = observer.summary()
        assert summary["total_duration_ms"] == 0.0
        assert summary["node_count"] == 0
        assert summary["nodes"] == {}
        assert summary["slowest_node"] is None


class TestWrapNode:
    def test_wrap_node_calls_original(self):
        observer = PipelineObserver()
        wrapped = wrap_node(_dummy_node, observer)
        result = wrapped({"trace_id": "t1"})
        assert result == {"output_key": "value"}

    def test_wrap_node_records_event(self):
        observer = PipelineObserver()
        wrapped = wrap_node(_dummy_node, observer)
        wrapped({"trace_id": "t1"})
        assert len(observer.events) == 1
        assert observer.events[0].node_name == "_dummy_node"
        assert "output_key" in observer.events[0].state_keys_out

    def test_wrap_node_preserves_name(self):
        observer = PipelineObserver()
        wrapped = wrap_node(_dummy_node, observer)
        assert wrapped.__name__ == "_dummy_node"

    def test_wrap_node_measures_duration(self):
        observer = PipelineObserver()
        wrapped = wrap_node(_slow_node, observer)
        wrapped({"trace_id": "t1"})
        assert observer.events[0].duration_ms >= 5  # at least 5ms for 10ms sleep

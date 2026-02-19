"""Observability hooks — timing, event capture, and pipeline monitoring."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class NodeEvent:
    """Record of a single node execution."""

    node_name: str
    trace_id: str
    started_at: float
    ended_at: float
    duration_ms: float
    state_keys_in: list[str]
    state_keys_out: list[str]


class PipelineObserver:
    """Collects NodeEvent records across a pipeline run."""

    def __init__(self) -> None:
        self.events: list[NodeEvent] = []
        self._pending: dict[str, tuple[float, list[str], str]] = {}

    def on_node_enter(self, node_name: str, state: dict) -> None:
        trace_id = state.get("trace_id", "")
        self._pending[node_name] = (time.monotonic(), list(state.keys()), trace_id)

    def on_node_exit(self, node_name: str, state: dict, result: dict) -> None:
        entry = self._pending.pop(node_name, None)
        if entry is None:
            return
        started_at, state_keys_in, trace_id = entry
        ended_at = time.monotonic()
        duration_ms = (ended_at - started_at) * 1000.0
        self.events.append(NodeEvent(
            node_name=node_name,
            trace_id=trace_id,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            state_keys_in=state_keys_in,
            state_keys_out=list(result.keys()),
        ))

    def summary(self) -> dict[str, Any]:
        if not self.events:
            return {
                "total_duration_ms": 0.0,
                "node_count": 0,
                "nodes": {},
                "slowest_node": None,
            }
        total_duration_ms = sum(e.duration_ms for e in self.events)
        nodes: dict[str, dict[str, Any]] = {}
        for e in self.events:
            nodes[e.node_name] = {
                "duration_ms": e.duration_ms,
                "state_keys_in": e.state_keys_in,
                "state_keys_out": e.state_keys_out,
            }
        slowest = max(self.events, key=lambda e: e.duration_ms)
        return {
            "total_duration_ms": total_duration_ms,
            "node_count": len(self.events),
            "nodes": nodes,
            "slowest_node": slowest.node_name,
        }


def wrap_node(fn: Callable, observer: PipelineObserver) -> Callable:
    """Wrap a graph node function to emit events via the observer."""
    node_name = getattr(fn, "__name__", str(fn))

    def wrapped(state: dict) -> dict:
        observer.on_node_enter(node_name, state)
        result = fn(state)
        observer.on_node_exit(node_name, state, result)
        return result

    wrapped.__name__ = node_name
    return wrapped

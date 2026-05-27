"""Per-tool call metrics with a rolling latency window. No external dependencies."""

from __future__ import annotations

import math
import threading
from collections import deque
from typing import Any


class _ToolStats:
    __slots__ = ("call_count", "error_count", "_latencies", "_lock")

    def __init__(self) -> None:
        self.call_count: int = 0
        self.error_count: int = 0
        self._latencies: deque[float] = deque(maxlen=1000)
        self._lock = threading.Lock()

    def record(self, elapsed_ms: float, *, error: bool) -> None:
        with self._lock:
            self.call_count += 1
            if error:
                self.error_count += 1
            self._latencies.append(elapsed_ms)

    def percentiles(self) -> dict[str, float]:
        with self._lock:
            data = sorted(self._latencies)
        n = len(data)
        if n == 0:
            return {"p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}

        def _pct(p: float) -> float:
            # Nearest-rank formula: ceil(p/100 * n) - 1, clamped to [0, n-1]
            idx = max(0, min(math.ceil(p / 100.0 * n) - 1, n - 1))
            return data[idx]

        return {"p50_ms": _pct(50), "p95_ms": _pct(95), "p99_ms": _pct(99)}

    def to_dict(self) -> dict[str, Any]:
        return {"calls": self.call_count, "errors": self.error_count, **self.percentiles()}


class Metrics:
    """Thread-safe per-tool call statistics."""

    def __init__(self) -> None:
        self._tools: dict[str, _ToolStats] = {}
        self._lock = threading.Lock()

    def record_call(self, tool: str, elapsed_ms: float, *, error: bool) -> None:
        with self._lock:
            if tool not in self._tools:
                self._tools[tool] = _ToolStats()
            stats = self._tools[tool]
        stats.record(elapsed_ms, error=error)

    def summary(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._tools)
        return {name: stats.to_dict() for name, stats in snapshot.items()}


_global: Metrics = Metrics()


def get_metrics() -> Metrics:
    return _global

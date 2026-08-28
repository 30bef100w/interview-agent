"""引擎节点指标（内存聚合，参考 Gua GraphMetricsRegistry）。"""
from __future__ import annotations

import threading
from collections import defaultdict


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._node_count: dict[str, int] = defaultdict(int)
        self._node_errors: dict[str, int] = defaultdict(int)
        self._node_duration_ms: dict[str, list[float]] = defaultdict(list)
        self._llm_calls = 0
        self._llm_errors = 0

    def record_node(self, node: str, duration_ms: float, *, error: str | None = None) -> None:
        with self._lock:
            self._node_count[node] += 1
            bucket = self._node_duration_ms[node]
            bucket.append(duration_ms)
            if len(bucket) > 500:
                del bucket[: len(bucket) - 500]
            if error:
                self._node_errors[node] += 1

    def record_llm(
        self,
        *,
        error: bool = False,
        duration_ms: float = 0.0,
        model: str = "",
    ) -> None:
        with self._lock:
            self._llm_calls += 1
            if error:
                self._llm_errors += 1
            if model:
                key = f"llm:{model}"
                self._node_count[key] += 1
                bucket = self._node_duration_ms[key]
                bucket.append(duration_ms)
                if len(bucket) > 500:
                    del bucket[: len(bucket) - 500]
                if error:
                    self._node_errors[key] += 1

    def snapshot(self) -> dict:
        with self._lock:
            nodes: dict[str, dict] = {}
            for name, count in self._node_count.items():
                durs = self._node_duration_ms.get(name) or []
                avg = sum(durs) / len(durs) if durs else 0.0
                p95 = sorted(durs)[int(len(durs) * 0.95)] if durs else 0.0
                nodes[name] = {
                    "count": count,
                    "errors": self._node_errors.get(name, 0),
                    "avg_ms": round(avg, 1),
                    "p95_ms": round(p95, 1),
                }
            return {
                "nodes": nodes,
                "llm": {
                    "calls": self._llm_calls,
                    "errors": self._llm_errors,
                },
            }


metrics_registry = MetricsRegistry()

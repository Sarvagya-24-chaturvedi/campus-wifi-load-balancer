"""
Server model for the campus Wi-Fi load balancer simulation.

Each access point / edge server tracks load, capacity, and queue state.
Response time is derived from utilization (scheduling-delay heuristic for demo).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class Server:
    """Simulated AP / server participating in load balancing."""

    id: int
    name: str
    max_capacity: float  # abstract units (bandwidth / CPU share)
    weight: float = 1.0  # operator-tunable preference in weighted algorithms
    base_response_ms: float = 12.0  # idle latency baseline
    failed: bool = False

    current_load: float = 0.0
    active_connections: int = 0
    queue_length: int = 0

    total_served: int = 0
    cumulative_latency_ms: float = 0.0

    _pending_work: deque[float] = field(default_factory=deque, repr=False)

    def available_capacity(self) -> float:
        """Headroom before hitting max_capacity."""
        return max(0.0, self.max_capacity - self.current_load)

    def utilization(self) -> float:
        """0..1 utilization for dashboard charts."""
        if self.max_capacity <= 0:
            return 0.0
        return min(1.0, self.current_load / self.max_capacity)

    def estimated_response_ms(self) -> float:
        """
        Non-linear growth with utilization (greedy latency estimate).

        Time complexity: O(1).
        """
        if self.failed:
            return float("inf")
        u = self.utilization()
        denom = max(1e-6, 1.0 - 0.85 * u)
        return self.base_response_ms / denom

    def snapshot(self) -> dict:
        """JSON-serializable view for API + UI."""
        return {
            "id": self.id,
            "name": self.name,
            "max_capacity": round(self.max_capacity, 2),
            "weight": round(self.weight, 2),
            "current_load": round(self.current_load, 2),
            "active_connections": self.active_connections,
            "queue_length": self.queue_length,
            "response_time_ms": round(self.estimated_response_ms(), 2)
            if not self.failed
            else None,
            "utilization": round(self.utilization(), 3),
            "failed": self.failed,
            "total_served": self.total_served,
        }

    def can_accept(self, min_slice: float = 0.0) -> bool:
        if self.failed:
            return False
        return self.available_capacity() >= min_slice

    def enqueue_work(self, work_units: float) -> None:
        """Attach new work to this server (increments queue + load)."""
        if self.failed:
            return
        self._pending_work.append(work_units)
        self.queue_length = len(self._pending_work)
        self.active_connections = self.queue_length
        self.current_load = min(self.max_capacity, self.current_load + work_units)

    def serve_tick(self, dt: float) -> tuple[int, float]:
        """
        Process a small time slice. Returns (completions_count, latency_sum_ms).

        Greedy local policy: drain work proportional to effective service rate.
        Complexity: O(k) where k is number of completed jobs this tick (typically small).
        """
        if self.failed or not self._pending_work:
            return 0, 0.0

        headroom = self.available_capacity() + 1e-6
        service_rate = self.max_capacity * (0.25 + 0.75 * (headroom / self.max_capacity))
        budget = max(0.0, service_rate * dt)

        completions = 0
        latency_batch = 0.0

        while budget > 0 and self._pending_work:
            front = self._pending_work[0]
            served = min(front, budget)
            front -= served
            budget -= served
            self.current_load = max(0.0, self.current_load - served)

            if front <= 1e-6:
                self._pending_work.popleft()
                latency = self.estimated_response_ms()
                self.total_served += 1
                self.cumulative_latency_ms += latency
                latency_batch += latency
                completions += 1
            else:
                self._pending_work[0] = front
                break

        self.queue_length = len(self._pending_work)
        self.active_connections = self.queue_length
        return completions, latency_batch
''''''
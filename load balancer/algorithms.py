"""
Load balancing algorithms with explicit ADA-style notes.

Design goals (course alignment):
- Greedy choice per request: pick the locally best server under a metric.
- Where appropriate, use a binary min-heap (heapq) for candidate ordering.
- Document asymptotic cost; n is the number of servers (here n <= 5, but complexity is stated generally).

All selectors skip failed servers. Ties break on lower server id for determinism.
"""

from __future__ import annotations

import heapq
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server import Server
    from simulator import Request


class LoadBalancingAlgorithm(ABC):
    """Strategy interface."""

    name: str

    @abstractmethod
    def select(self, servers: list["Server"], request: "Request") -> "Server" | None:
        """Return target server or None if no healthy capacity exists."""

    def complexity_note(self) -> str:
        """Human-readable complexity summary for README / UI."""
        return "See docstring of concrete algorithm."


class RoundRobin(LoadBalancingAlgorithm):
    """
    Classic Round Robin over healthy servers.

    Time complexity: O(1) amortized per assignment (pointer increment), O(n) worst case
    to skip failed servers in pathological cases.
    Space complexity: O(1).
    """

    name = "round_robin"

    def __init__(self) -> None:
        self._cursor = 0

    def select(self, servers: list["Server"], request: "Request") -> "Server" | None:
        if not servers:
            return None
        n = len(servers)
        for step in range(n):
            idx = (self._cursor + step) % n
            candidate = servers[idx]
            if not candidate.failed and candidate.can_accept(request.work_units):
                self._cursor = (idx + 1) % n
                return candidate
        return None

    def complexity_note(self) -> str:
        return "Per request: O(1) amortized pointer move; O(n) worst-case scan skipping failed nodes."


class LeastConnections(LoadBalancingAlgorithm):
    """
    Greedy: choose server with smallest active_connections.

    Implementation uses heapq (binary min-heap) built fresh per decision.
    Build heap: O(n); pop best: O(log n) => O(n) overall for small n.

    Space complexity: O(n) for the heap array.
    """

    name = "least_connections"

    def select(self, servers: list["Server"], request: "Request") -> "Server" | None:
        heap: list[tuple[int, int, "Server"]] = []
        for s in servers:
            if s.failed or not s.can_accept(request.work_units):
                continue
            # (connections, server_id, server) — id stabilizes ties
            heap.append((s.active_connections, s.id, s))
        if not heap:
            return None
        heapq.heapify(heap)
        _, _, best = heapq.heappop(heap)
        return best

    def complexity_note(self) -> str:
        return "Per request: O(n) heapify + O(log n) pop => O(n); greedy on minimum connections."


class WeightedLeastLoad(LoadBalancingAlgorithm):
    """
    Greedy score: normalized load penalized by capacity and operator weight.

    score = (current_load + pending_request) / (max_capacity * weight)
    Pick server with minimum score (heap-backed).

    Time complexity: O(n) to heapify candidate scores.
    Space complexity: O(n).
    """

    name = "weighted_least_load"

    def select(self, servers: list["Server"], request: "Request") -> "Server" | None:
        heap: list[tuple[float, int, "Server"]] = []
        wu = request.work_units
        for s in servers:
            if s.failed or not s.can_accept(wu):
                continue
            denom = max(1e-6, s.max_capacity * max(0.05, s.weight))
            projected = s.current_load + wu
            score = projected / denom
            heap.append((score, s.id, s))
        if not heap:
            return None
        heapq.heapify(heap)
        _, _, best = heapq.heappop(heap)
        return best

    def complexity_note(self) -> str:
        return "Per request: O(n) greedy via min-heap on weighted utilization score."


class ResponseTimeBased(LoadBalancingAlgorithm):
    """
    Greedy: pick healthy server with lowest estimated_response_ms after assignment.

    Uses a min-heap ordered by simulated post-assignment latency.

    Time complexity: O(n) heap operations.
    Space complexity: O(n).
    """

    name = "response_time"

    def select(self, servers: list["Server"], request: "Request") -> "Server" | None:
        wu = request.work_units
        heap: list[tuple[float, int, "Server"]] = []
        for s in servers:
            if s.failed or not s.can_accept(wu):
                continue
            # Temporary mutation to estimate greedy one-step lookahead
            s.current_load += wu
            est = s.estimated_response_ms()
            s.current_load -= wu
            heap.append((est, s.id, s))
        if not heap:
            return None
        heapq.heapify(heap)
        _, _, best = heapq.heappop(heap)
        return best

    def complexity_note(self) -> str:
        return "Per request: O(n) greedy lookahead + min-heap; optimizes instantaneous predicted latency."


def build_registry() -> dict[str, LoadBalancingAlgorithm]:
    """Factory of named strategies for the simulator / API."""
    strategies: Iterable[LoadBalancingAlgorithm] = (
        RoundRobin(),
        LeastConnections(),
        WeightedLeastLoad(),
        ResponseTimeBased(),
    )
    return {s.name: s for s in strategies}


def list_algorithm_metadata() -> list[dict]:
    """Expose complexity blurbs to the UI."""
    meta = []
    for algo in build_registry().values():
        meta.append({"name": algo.name, "complexity": algo.complexity_note()})
    return meta

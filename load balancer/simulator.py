"""
Discrete-time campus Wi-Fi simulator.

Coordinates random request generation, algorithmic assignment, ticks,
and metrics (throughput, latency, fairness).
"""

from __future__ import annotations

import itertools
import random
import threading
import time
from collections import deque, defaultdict
from dataclasses import dataclass, field

from algorithms import LoadBalancingAlgorithm, RoundRobin, build_registry
from server import Server


@dataclass
class Request:
    """Synthetic client request traversing the simulated edge."""

    id: int
    user_type: str  # student | faculty | lab | malicious_bot (simulation)
    priority: int  # 1 (highest) .. 5 (lowest) — used for weighting work units
    size: float  # abstract bytes / flow size
    ip_address: str = "127.0.0.1"
    work_units: float = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "work_units",
            max(0.5, self.size) * (1.0 + (self.priority - 1) * 0.15),
        )


class CampusSimulator:
    """
    Thread-safe simulation kernel used by FastAPI routes.

    Greedy assignment: each request is placed immediately using the active strategy.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._servers = self._default_topology()
        self._algorithms = build_registry()
        # Fresh RR instance so restarts do not share cursor unexpectedly
        self._algorithms["round_robin"] = RoundRobin()
        self.active_algorithm = "weighted_least_load"
        self._next_request_id = itertools.count(1)
        self.sim_time = 0.0

        self.assignments: int = 0
        self.rejected: int = 0
        self.blocked_requests: int = 0
        self.waf_enabled: bool = False
        self.ddos_sustained: bool = False
        self.completed: int = 0
        self.total_latency_ms: float = 0.0
        self.latency_samples: int = 0
        self._throughput_window: deque[float] = deque(maxlen=120)

        # IP Tracking for Rate Limiting
        self.ip_history: defaultdict[str, list[float]] = defaultdict(list)

        self.history_seconds: deque[float] = deque(maxlen=200)
        self.history_throughput: deque[float] = deque(maxlen=200)
        self.history_latency: deque[float] = deque(maxlen=200)
        self.history_fairness: deque[float] = deque(maxlen=200)

        self.last_assignments: list[dict] = []

        self._started_at = time.time()
        self._last_tick_wall = time.time()

    @staticmethod
    def _default_topology() -> list[Server]:
        """Five servers with heterogeneous capacities (typical campus mix)."""
        return [
            Server(1, "Hostel Block A AP", max_capacity=120, weight=1.0, base_response_ms=10),
            Server(2, "Hostel Block B AP", max_capacity=100, weight=1.1, base_response_ms=11),
            Server(3, "Academic Wing Wi-Fi", max_capacity=150, weight=1.3, base_response_ms=9),
            Server(4, "Lab / Research VLAN", max_capacity=90, weight=0.9, base_response_ms=13),
            Server(5, "Library Edge Node", max_capacity=110, weight=1.0, base_response_ms=10),
        ]

    def set_algorithm(self, name: str) -> bool:
        with self._lock:
            if name not in self._algorithms:
                return False
            self.active_algorithm = name
            return True

    def algorithm(self) -> LoadBalancingAlgorithm:
        with self._lock:
            return self._algorithms[self.active_algorithm]

    def servers_snapshot(self) -> list[dict]:
        with self._lock:
            return [s.snapshot() for s in self._servers]

    def random_request(self) -> Request:
        user_type = random.choices(
            ["student", "faculty", "lab"],
            weights=[0.65, 0.25, 0.10],
            k=1,
        )[0]
        priority = random.choices([1, 2, 3, 4, 5], weights=[0.1, 0.2, 0.35, 0.25, 0.1], k=1)[0]
        size = round(random.uniform(2.0, 25.0), 2)
        rid = next(self._next_request_id)
        # Generate a random 10.0.x.x IP for normal traffic
        ip_addr = f"10.0.{random.randint(0, 5)}.{random.randint(1, 254)}"
        return Request(rid, user_type, priority, size, ip_addr)

    def generate_request(self) -> Request:
        """Public helper used by /generate_request."""
        return self.random_request()

    def set_waf(self, enabled: bool) -> None:
        """Enable or disable AI-WAF / IDS-style blocking for synthetic malicious traffic."""
        with self._lock:
            self.waf_enabled = bool(enabled)

    def set_ddos_sustained(self, active: bool) -> None:
        """Toggle sustained L7 flood: each simulation tick injects many malicious_bot requests."""
        with self._lock:
            self.ddos_sustained = bool(active)

    def simulate_ddos(self) -> dict:
        """
        Generate 150 high-volume bot requests (cybersecurity exercise).
        Does not use random_request(); each request uses the exact SAME IP to trigger rate limits.
        """
        blocked = 0
        assigned = 0
        rejected_other = 0
        for _ in range(150):
            rid = next(self._next_request_id)
            req = Request(rid, "malicious_bot", 5, 50.0, "192.168.1.99")
            out = self.assign_request(req)
            if out.get("ok"):
                assigned += 1
            elif out.get("error") == "waf_blocked":
                blocked += 1
            else:
                rejected_other += 1
        return {
            "simulated": 150,
            "blocked": blocked,
            "assigned": assigned,
            "rejected_other": rejected_other,
        }

    def assign_request(self, request: Request, algorithm_name: str | None = None) -> dict:
        """
        Greedy assignment: pick server via strategy, enqueue immediately.
        """
        with self._lock:
            return self._assign_request_locked(request, algorithm_name)

    def _assign_request_locked(self, request: Request, algorithm_name: str | None = None) -> dict:
        """
        Same as assign_request but must be called with ``self._lock`` already held.
        """
        # IP-Based Rate Limiting WAF Logic
        if self.waf_enabled:
            now = time.time()
            history = self.ip_history[request.ip_address]
            
            # Clean up timestamps older than 1.5 seconds
            while history and now - history[0] > 1.5:
                history.pop(0)
            
            history.append(now)
            
            # If an IP makes > 5 requests in 1.5s, block it
            if len(history) > 5:
                self.blocked_requests += 1
                return {
                    "ok": False,
                    "error": "waf_blocked",
                    "request": self.serialize_request(request),
                }

        algo_name = algorithm_name or self.active_algorithm
        algo = self._algorithms.get(algo_name)
        if algo is None:
            return {"ok": False, "error": "unknown_algorithm", "request": self.serialize_request(request)}

        target = algo.select(self._servers, request)
        if target is None:
            self.rejected += 1
            return {
                "ok": False,
                "error": "no_capacity",
                "request": self.serialize_request(request),
                "algorithm": algo_name,
            }

        target.enqueue_work(request.work_units)
        self.assignments += 1
        record = {
            "request_id": request.id,
            "server_id": target.id,
            "server_name": target.name,
            "algorithm": algo_name,
            "user_type": request.user_type,
            "priority": request.priority,
            "work_units": round(request.work_units, 2),
            "ip_address": request.ip_address,
        }
        self.last_assignments.insert(0, record)
        self.last_assignments = self.last_assignments[:40]
        return {"ok": True, "assignment": record}

    def tick(self, dt: float | None = None) -> dict:
        """Advance simulation time, drain queues, refresh rolling metrics."""
        now = time.time()
        with self._lock:
            if dt is None:
                dt = max(0.05, min(0.5, now - self._last_tick_wall))
            self._last_tick_wall = now
            self.sim_time += dt

            if self.ddos_sustained:
                # Sustained L7 attack: flood malicious_bot traffic from SAME IP
                for _ in range(40):
                    rid = next(self._next_request_id)
                    req = Request(rid, "malicious_bot", 5, 50.0, "192.168.1.99")
                    self._assign_request_locked(req, None)

            completions = 0
            latency_sum = 0.0
            for server in self._servers:
                done, lat = server.serve_tick(dt)
                completions += done
                latency_sum += lat

            self.completed += completions
            if completions > 0:
                self.total_latency_ms += latency_sum
                self.latency_samples += completions

            rps = completions / dt if dt > 0 else 0.0
            self._throughput_window.append(rps)

            fairness = self._fairness_index_locked()
            avg_lat = (
                (self.total_latency_ms / self.latency_samples) if self.latency_samples else 0.0
            )
            smooth_tp = sum(self._throughput_window) / max(1, len(self._throughput_window))

            self.history_seconds.append(round(self.sim_time, 2))
            self.history_throughput.append(round(smooth_tp, 3))
            self.history_latency.append(round(avg_lat, 3))
            self.history_fairness.append(round(fairness, 4))

            return {
                "dt": round(dt, 4),
                "completions_this_tick": completions,
                "rolling_throughput_rps": round(smooth_tp, 3),
                "average_latency_ms": round(avg_lat, 3),
                "fairness_jain": round(fairness, 4),
                "sim_time": round(self.sim_time, 2),
            }

    def metrics(self) -> dict:
        """Aggregate metrics for /metrics + dashboard cards."""
        with self._lock:
            elapsed = max(1e-6, time.time() - self._started_at)
            avg_lat = (
                (self.total_latency_ms / self.latency_samples) if self.latency_samples else 0.0
            )
            fairness = self._fairness_index_locked()
            smooth_tp = sum(self._throughput_window) / max(1, len(self._throughput_window))
            return {
                "uptime_sec": round(elapsed, 2),
                "sim_time": round(self.sim_time, 2),
                "assignments": self.assignments,
                "completed": self.completed,
                "rejected": self.rejected,
                "blocked_requests": self.blocked_requests,
                "waf_enabled": self.waf_enabled,
                "ddos_active": self.ddos_sustained,
                "average_latency_ms": round(avg_lat, 3),
                "throughput_rps": round(self.completed / elapsed, 3),
                "rolling_throughput_rps": round(smooth_tp, 3),
                "fairness_jain": round(fairness, 4),
                "active_algorithm": self.active_algorithm,
                "servers": [s.snapshot() for s in self._servers],
                "recent_assignments": list(self.last_assignments),
                "history": {
                    "sim_time": list(self.history_seconds),
                    "throughput_rps": list(self.history_throughput),
                    "latency_ms": list(self.history_latency),
                    "fairness": list(self.history_fairness),
                },
            }

    def set_server_weight(self, server_id: int, weight: float) -> bool:
        with self._lock:
            for s in self._servers:
                if s.id == server_id:
                    s.weight = max(0.05, float(weight))
                    return True
            return False

    def set_server_failure(self, server_id: int, failed: bool) -> bool:
        with self._lock:
            for s in self._servers:
                if s.id == server_id:
                    s.failed = failed
                    if failed:
                        s._pending_work.clear()
                        s.queue_length = 0
                        s.active_connections = 0
                        s.current_load = 0.0
                    return True
            return False

    def algorithms(self) -> list[dict]:
        from algorithms import list_algorithm_metadata
        return list_algorithm_metadata()

    def _fairness_index_locked(self) -> float:
        """
        Jain's fairness index on per-server utilization vector.
        """
        utils = [s.utilization() for s in self._servers if not s.failed]
        if not utils:
            return 1.0
        num = sum(utils) ** 2
        den = len(utils) * sum(u * u for u in utils)
        if den <= 0:
            return 1.0
        return float(num / den)

    @staticmethod
    def serialize_request(req: Request) -> dict:
        """JSON-safe representation for API clients."""
        return {
            "id": req.id,
            "user_type": req.user_type,
            "priority": req.priority,
            "size": req.size,
            "ip_address": req.ip_address,
            "work_units": round(req.work_units, 2),
        }
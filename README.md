[README.md](https://github.com/user-attachments/files/26894621/README.md)
# Algorithm-Based Load Balancer for Campus / Hostel Wi-Fi

Simulation-only teaching project that models heterogeneous access points (APs) serving mixed student, faculty, and lab traffic. A FastAPI backend coordinates greedy load-balancing strategies while a lightweight HTML dashboard visualizes queues, utilization, and rolling throughput/latency.

## Problem statement

Campus and hostel Wi-Fi is a **multi-tenant, capacity-constrained** edge network. Clients arrive continuously with different priorities (labs vs. casual student browsing). Without intelligent steering, a few APs can saturate while neighbors stay idle, inflating latency and dropping fairness.

This project answers: **How do classic algorithmic policies redistribute synthetic load across five APs, and what metrics expose the trade-offs?** No packets are sent on a real network—the simulator advances in discrete time steps driven by API polling.

## Architecture

| File | Responsibility |
| --- | --- |
| `server.py` | `Server` class: capacity, weight, failure flag, queue-backed work, latency heuristic. |
| `algorithms.py` | Modular strategies (`RoundRobin`, `LeastConnections`, `WeightedLeastLoad`, `ResponseTimeBased`) with documented complexity. |
| `simulator.py` | `Request` + `CampusSimulator`: random traffic, greedy assignment, Jain fairness, metrics history. |
| `app.py` | FastAPI routes + static UI hosting. |
| `static/` | Dashboard (HTML/CSS/JS + Chart.js CDN). |

## Algorithms (greedy + heaps)

All strategies **skip failed APs** and refuse assignments when no server has spare capacity.

1. **Round Robin (`round_robin`)** — cycles healthy servers. *Complexity:* `O(1)` amortized pointer update; up to `O(n)` scans when failures dominate.
2. **Least Connections (`least_connections`)** — `heapq` min-heap on `(active_connections, server_id)`. *Complexity:* `O(n)` `heapify` + `O(log n)` pop.
3. **Weighted Least Load (`weighted_least_load`)** — min-heap on projected utilization `(load + work) / (capacity * weight)`. *Complexity:* `O(n)` greedy scoring.
4. **Response Time Based (`response_time`)** — min-heap on estimated latency after a one-step lookahead mutation. *Complexity:* `O(n)` greedy evaluation.

## CN + ADA concepts demonstrated

- **Computer networks:** edge load, queuing intuition, utilization, synthetic VLAN/AP heterogeneity, failure isolation.
- **Algorithms & data structures:** binary min-heaps (`heapq`) for greedy server selection, modular strategy pattern, asymptotic notes in code/docstrings, fairness quantified via **Jain’s index** on utilization vectors.

## Metrics

- **Average response time:** cumulative simulated service latency divided by completed jobs.
- **Throughput:** completed jobs / uptime (and a short rolling average for jitter smoothing).
- **Fairness:** Jain’s fairness index in `[0,1]` (1 is perfectly balanced utilization across healthy APs).

## How to run

**Windows (PowerShell)**

```powershell
Set-Location "C:\Users\Sarva\OneDrive\Desktop\load balancer"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
```

**macOS / Linux**

```bash
cd "/path/to/load balancer"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open `http://127.0.0.1:8000/` for the dashboard or `http://127.0.0.1:8000/docs` for OpenAPI.

### Core API surface

- `POST /generate_request` — synthesize a randomized `Request`.
- `GET /get_servers` — snapshot AP stats (read-only).
- `POST /assign_request` — JSON body `{"request": {...}, "algorithm": "optional"}`.
- `GET /metrics` — advances the simulator clock, returns KPIs, history arrays, and recent assignments.

Additional helpers used by the UI:

- `POST /algorithm` — hot-swap the active strategy.
- `POST /server/{id}/weight` — adjust weights for weighted least load.
- `POST /server/{id}/failure` — drain queues and mark an AP offline.
- `POST /burst?count=24` — rapid demo traffic.

## Sample test run

With `uvicorn` running (default base URL `http://127.0.0.1:8000`):

```bash
python sample_run.py
```

To point at another host/port:

```bash
set LOAD_BALANCER_BASE=http://127.0.0.1:8010   # Windows cmd
# PowerShell: $env:LOAD_BALANCER_BASE="http://127.0.0.1:8010"
python sample_run.py
```

Example console excerpt:

```
GET /health -> {'status': 'ok'}
GET /get_servers -> 5 servers
POST /generate_request -> {'id': 7, 'user_type': 'student', ...}
POST /assign_request -> {"ok": true, "assignment": {...}}
GET /metrics (summary):
{
  "assignments": 32,
  "completed": 18,
  "average_latency_ms": 14.125,
  "throughput_rps": 0.412,
  "fairness_jain": 0.973,
  "active_algorithm": "round_robin"
}
```
## Extending the project

- **Admission control:** reject low-priority students when utilization > threshold (add policy layer before `assign_request`).
- **Sticky sessions:** add affinity maps so a subset of users pins to an AP unless it fails.
- **Trace replay:** replace `random_request()` with CSV-driven arrivals for reproducible experiments.
- **WebSockets:** push `/metrics` updates instead of polling for denser timelines.
- **Testing:** add `pytest` suites that freeze RNG seeds and assert deterministic heap choices.

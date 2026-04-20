"""
Sample scripted exercise against the running API (stdlib only).

Usage (from project root, with uvicorn already running on :8000):
    python sample_run.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request


BASE = os.environ.get("LOAD_BALANCER_BASE", "http://127.0.0.1:8000")


def call(method: str, path: str, payload: dict | None = None) -> dict:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    print("Campus Wi-Fi load balancer - sample API walkthrough\n")

    try:
        health = call("GET", "/health")
        print("GET /health ->", health)

        servers = call("GET", "/get_servers")
        print("\nGET /get_servers ->", len(servers["servers"]), "servers")

        req = call("POST", "/generate_request")
        print("\nPOST /generate_request ->", req["request"])

        assign = call(
            "POST",
            "/assign_request",
            {"request": req["request"], "algorithm": "least_connections"},
        )
        print("\nPOST /assign_request ->", json.dumps(assign, indent=2))

        call("POST", "/algorithm", {"algorithm": "round_robin"})
        call("POST", "/burst?count=30", None)

        metrics = call("GET", "/metrics")
        print("\nGET /metrics (summary):")
        summary = {
            k: metrics[k]
            for k in (
                "uptime_sec",
                "assignments",
                "completed",
                "average_latency_ms",
                "throughput_rps",
                "rolling_throughput_rps",
                "fairness_jain",
                "active_algorithm",
            )
        }
        print(json.dumps(summary, indent=2))
        print("\nSample run finished OK.")
        return 0
    except urllib.error.URLError as exc:
        print("Could not reach API. Start the server first:", file=sys.stderr)
        print("  uvicorn app:app --reload --port 8000", file=sys.stderr)
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

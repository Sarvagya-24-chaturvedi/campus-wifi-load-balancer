"""
FastAPI entrypoint exposing the campus Wi-Fi load balancer simulation.

All long-lived state lives in a single `CampusSimulator` instance.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Ensure simulator.py is in the same directory and contains these classes
from simulator import CampusSimulator, Request

STATIC_DIR = Path(__file__).parent / "static"

sim = CampusSimulator()

app = FastAPI(
    title="Campus Wi-Fi Algorithmic Load Balancer",
    version="1.0.0",
    description="Simulation-only API for teaching CN + ADA load balancing.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestPayload(BaseModel):
    id: int
    user_type: str
    priority: int = Field(ge=1, le=5)
    size: float = Field(gt=0)
    ip_address: str | None = None


class AssignBody(BaseModel):
    request: RequestPayload
    algorithm: str | None = None


class AlgorithmBody(BaseModel):
    algorithm: str


class WeightBody(BaseModel):
    weight: float = Field(gt=0)


class FailureBody(BaseModel):
    failed: bool


class WafBody(BaseModel):
    enabled: bool


class DdosBody(BaseModel):
    active: bool


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/generate_request")
def generate_request() -> dict:
    """Create a randomized campus request (does not assign)."""
    req = sim.generate_request()
    return {"request": sim.serialize_request(req)}


@app.get("/get_servers")
def get_servers() -> dict:
    """Return AP snapshots (read-only; use /metrics to advance simulation time)."""
    return {"servers": sim.servers_snapshot()}


@app.post("/assign_request")
def assign_request(body: AssignBody) -> dict:
    """Greedy assignment of a client request to a server."""
    req = Request(
        id=body.request.id,
        user_type=body.request.user_type,
        priority=body.request.priority,
        size=body.request.size,
        ip_address=body.request.ip_address or "127.0.0.1",
    )
    return sim.assign_request(req, algorithm_name=body.algorithm)


@app.get("/metrics")
def metrics() -> dict:
    """Rolling metrics for charts + KPI cards."""
    tick_info = sim.tick()
    core = sim.metrics()
    core["tick"] = tick_info
    core["algorithms"] = sim.algorithms()
    return core


@app.get("/algorithms")
def algorithms() -> dict:
    return {"algorithms": sim.algorithms(), "active": sim.active_algorithm}


@app.post("/algorithm")
def set_algorithm(body: AlgorithmBody) -> dict:
    ok = sim.set_algorithm(body.algorithm)
    if not ok:
        raise HTTPException(status_code=400, detail="Unknown algorithm")
    return {"active": sim.active_algorithm}


@app.post("/server/{server_id}/weight")
def set_weight(server_id: int, body: WeightBody) -> dict:
    ok = sim.set_server_weight(server_id, body.weight)
    if not ok:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"server_id": server_id, "weight": body.weight}


@app.post("/server/{server_id}/failure")
def set_failure(server_id: int, body: FailureBody) -> dict:
    ok = sim.set_server_failure(server_id, body.failed)
    if not ok:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"server_id": server_id, "failed": body.failed}


@app.post("/waf")
def set_waf(body: WafBody) -> dict:
    """Toggle AI-WAF / IDS simulation: blocks synthetic malicious_bot traffic when enabled."""
    sim.set_waf(body.enabled)
    return {"waf_enabled": sim.waf_enabled}


@app.post("/simulate_ddos")
def simulate_ddos() -> dict:
    """Flood the simulator with 150 malicious_bot requests (DDoS exercise)."""
    return sim.simulate_ddos()


@app.post("/ddos")
def set_ddos(body: DdosBody) -> dict:
    """Start or stop sustained L7 DDoS simulation (backend floods each metrics/tick)."""
    sim.set_ddos_sustained(body.active)
    return {"ddos_active": sim.ddos_sustained}


@app.post("/burst")
def burst(count: int = Query(24, ge=1, le=200)) -> dict:
    """Convenience demo endpoint: generate+assign many requests quickly."""
    count = max(1, min(count, 200))
    results = []
    for _ in range(count):
        r = sim.generate_request()
        results.append(sim.assign_request(r))
    return {"count": count, "results": results}


if STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=STATIC_DIR, html=True), name="ui")


@app.get("/", response_model=None)
def root() -> FileResponse | JSONResponse:
    index = STATIC_DIR / "index.html"
    if not index.exists():
        return JSONResponse(
            {"message": "static/index.html missing", "docs": "/docs"},
            status_code=500,
        )
    return FileResponse(index)
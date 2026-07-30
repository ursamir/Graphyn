"""
Bounded Context:  REST API Layer
Responsibility:   Lightweight in-process API metrics collection and snapshots.
Owns:             record_request(), snapshot_metrics().
Public Surface:   record_request(path, method, status_code, duration_s),
                  snapshot_metrics().
Must NOT:         Depend on app.domain or execution runtime internals.
Dependencies:     stdlib only (threading, time, collections).
Reason To Change: Metrics schema changes or exporter backend is introduced.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Any

_LOCK = threading.Lock()
_START_TS = time.time()
_TOTAL_REQUESTS = 0
_TOTAL_ERRORS = 0
_BY_STATUS: dict[str, int] = defaultdict(int)
_BY_ROUTE: dict[str, int] = defaultdict(int)
_LATENCIES = deque(maxlen=2000)


def record_request(path: str, method: str, status_code: int, duration_s: float) -> None:
    """Record one API request metric sample."""
    global _TOTAL_REQUESTS, _TOTAL_ERRORS
    route_key = f"{method.upper()} {path}"
    with _LOCK:
        _TOTAL_REQUESTS += 1
        if status_code >= 500:
            _TOTAL_ERRORS += 1
        _BY_STATUS[str(status_code)] += 1
        _BY_ROUTE[route_key] += 1
        _LATENCIES.append(max(0.0, float(duration_s)))


def snapshot_metrics() -> dict[str, Any]:
    """Return a point-in-time metrics snapshot."""
    with _LOCK:
        lat = list(_LATENCIES)
        req_total = _TOTAL_REQUESTS
        err_total = _TOTAL_ERRORS
        by_status = dict(_BY_STATUS)
        by_route = dict(_BY_ROUTE)
    if lat:
        lat_sorted = sorted(lat)
        p50 = lat_sorted[int(0.50 * (len(lat_sorted) - 1))]
        p95 = lat_sorted[int(0.95 * (len(lat_sorted) - 1))]
        p99 = lat_sorted[int(0.99 * (len(lat_sorted) - 1))]
        avg = sum(lat) / len(lat)
    else:
        p50 = p95 = p99 = avg = 0.0
    uptime_s = max(0.0, time.time() - _START_TS)
    rps = req_total / uptime_s if uptime_s > 0 else 0.0
    return {
        "uptime_s": round(uptime_s, 3),
        "requests_total": req_total,
        "errors_5xx_total": err_total,
        "requests_per_second": round(rps, 4),
        "latency_s": {
            "avg": round(avg, 6),
            "p50": round(p50, 6),
            "p95": round(p95, 6),
            "p99": round(p99, 6),
            "sample_size": len(lat),
        },
        "by_status": by_status,
        "by_route": by_route,
    }

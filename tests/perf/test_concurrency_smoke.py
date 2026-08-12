"""Concurrency smoke test -- not a load/perf harness.

A correctness check under light concurrency, against the same SQLite-backed
TestClient as the rest of the API suite: do concurrent writes ever get
dropped or corrupt the aggregate counts?

SQLite serializes writers and TestClient runs in-process, so this only
catches gross bugs -- it says nothing about real concurrent load against
Postgres. A real perf harness (locust/k6 against the live docker-compose
stack) is out of scope here; see "Gaps & future work" in TEST_STRATEGY.md.
"""
from concurrent.futures import ThreadPoolExecutor

import pytest

pytestmark = pytest.mark.perf

STATION_COUNT = 20
REPORTS_PER_STATION = 5


def test_concurrent_ingests_are_not_lost_or_corrupted(client):
    payloads = [
        {
            "station_id": f"STATION-{station}",
            "timestamp": f"2024-06-01T{10 + report:02d}:00:00Z",
            "connectivity_status": "online",
            "latency_ms": 50,
            "error_count": 0,
            "firmware_version": "v1.0.0",
        }
        for station in range(STATION_COUNT)
        for report in range(REPORTS_PER_STATION)
    ]

    def ingest(payload):
        return client.post("/reports", json=payload)

    with ThreadPoolExecutor(max_workers=10) as pool:
        responses = list(pool.map(ingest, payloads))

    assert all(r.status_code == 201 for r in responses)

    stations = client.get("/stations").json()
    assert len(stations) == STATION_COUNT

    metrics = client.get("/metrics/summary").json()
    assert metrics["total_stations"] == STATION_COUNT

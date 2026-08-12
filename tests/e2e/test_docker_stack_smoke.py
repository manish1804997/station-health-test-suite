"""End-to-end smoke tests against the real docker-compose stack (FastAPI + Postgres).

These fire real HTTP requests at an already-running server instead of
using FastAPI's TestClient -- the only layer that actually exercises the
Postgres-backed deployment path (psycopg2, real ASGI server, real socket).

Needs `docker compose up` running first (see the `e2e-docker` CI job). If
it's not up, the `api` fixture's health check notices and skips the whole
module, so running locally without the stack just skips cleanly.
"""
import uuid

import httpx
import pytest
from http_client_handler import StationHealthClient

from config import SERVICE_URL

pytestmark = pytest.mark.e2e


@pytest.fixture(scope="session")
def api():
    client = StationHealthClient(SERVICE_URL)
    try:
        resp = client.health()
    except httpx.HTTPError:
        pytest.skip(f"docker-compose stack not reachable at {SERVICE_URL}")
    if resp.status_code != 200:
        pytest.skip(f"docker-compose stack unhealthy at {SERVICE_URL}: {resp.status_code}")
    yield client
    client.close()


def test_health_check_reports_ok(api):
    resp = api.health()
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_ingest_and_read_back_round_trip_through_postgres(api):
    # Giving the station a unique ID per run keeps this test independent of
    # whatever else got ingested into the shared Postgres instance during
    # this CI run -- there's no per-test isolation at this layer, unlike
    # the SQLite-backed API suite.
    station_id = f"E2E-{uuid.uuid4().hex[:8]}"
    payload = {
        "station_id": station_id,
        "timestamp": "2024-06-01T10:00:00Z",
        "connectivity_status": "online",
        "latency_ms": 120,
        "error_count": 2,
        "firmware_version": "v2.3.1",
    }

    post_resp = api.post_report(payload)
    assert post_resp.status_code == 201
    assert post_resp.json() == {
        "station_id": station_id,
        "hygiene_score": 84.0,
        "flagged": False,
    }

    status_resp = api.get_station_status(station_id)
    assert status_resp.status_code == 200
    assert status_resp.json()["hygiene_score"] == 84.0


def test_unknown_station_returns_404(api):
    resp = api.get_station_status(f"DOES-NOT-EXIST-{uuid.uuid4().hex}")
    assert resp.status_code == 404


def test_metrics_summary_is_reachable_and_well_formed(api):
    resp = api.get_metrics_summary()
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_stations"] >= 0
    assert isinstance(body["flagged_count"], int)

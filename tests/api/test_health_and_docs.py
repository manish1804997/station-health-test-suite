"""Smoke tests for the endpoints that aren't really business logic but still
need to keep working -- the health check, the dashboard, and the OpenAPI
schema that /docs and anyone generating a client from this API relies on.
"""
import pytest

pytestmark = pytest.mark.api


def test_health_check(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_dashboard_root_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_openapi_schema_exposes_all_documented_endpoints(client):
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    expected_paths = (
        "/reports",
        "/stations",
        "/stations/{station_id}/status",
        "/stations/poor-hygiene",
        "/metrics/summary",
    )
    for expected in expected_paths:
        assert expected in paths


def test_docs_ui_is_reachable(client):
    resp = client.get("/docs")
    assert resp.status_code == 200

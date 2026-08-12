"""Integration tests for POST /reports.

These go through the whole stack for real: FastAPI routing, pydantic
validation, the scoring module, and an actual database write (SQLite,
isolated per test, but a real write nonetheless).
"""
import pytest
from factories import report_payload

pytestmark = pytest.mark.api


class TestIngestValidReport:
    def test_returns_201_with_computed_score_and_flag(self, post_report):
        # online, 0 errors, 120ms latency -> 100 - 6 = 94, not flagged
        resp = post_report(latency_ms=120, error_count=0)
        assert resp.status_code == 201
        assert resp.json() == {
            "station_id": "STATION-001",
            "hygiene_score": 94.0,
            "flagged": False,
        }

    def test_response_does_not_leak_raw_telemetry_fields(self, post_report):
        # ReportOut is meant to be a narrow, deliberate response shape. If
        # someone later returns the ORM object directly and it accidentally
        # widens, this should catch it instead of letting extra fields leak
        # out silently.
        resp = post_report()
        assert set(resp.json().keys()) == {"station_id", "hygiene_score", "flagged"}

    def test_previously_unknown_station_is_created_implicitly(self, client, post_report):
        post_report(station_id="STATION-NEW")
        station_ids = {s["station_id"] for s in client.get("/stations").json()}
        assert "STATION-NEW" in station_ids

    def test_score_exactly_at_threshold_is_not_flagged(self, post_report):
        # An offline-only penalty lands exactly on 60, the flagging
        # threshold. Since is_flagged uses strict `<`, this station should
        # still read as healthy, not flagged.
        resp = post_report(connectivity_status="offline", latency_ms=0, error_count=0)
        body = resp.json()
        assert body["hygiene_score"] == 60.0
        assert body["flagged"] is False

    def test_score_just_below_threshold_is_flagged(self, post_report):
        resp = post_report(connectivity_status="offline", latency_ms=20, error_count=0)
        body = resp.json()
        assert body["hygiene_score"] == 59.0
        assert body["flagged"] is True


class TestIngestValidation:
    @pytest.mark.parametrize(
        "overrides",
        [
            {"station_id": ""},
            {"connectivity_status": "flaky"},  # not in the online/offline enum
            {"latency_ms": -1},
            {"error_count": -1},
            {"firmware_version": ""},
        ],
        ids=[
            "empty-station-id",
            "invalid-connectivity",
            "negative-latency",
            "negative-errors",
            "empty-firmware",
        ],
    )
    def test_rejects_invalid_payload_with_422(self, post_report, overrides):
        resp = post_report(**overrides)
        assert resp.status_code == 422

    @pytest.mark.parametrize(
        "missing_field",
        [
            "station_id",
            "timestamp",
            "connectivity_status",
            "latency_ms",
            "error_count",
            "firmware_version",
        ],
    )
    def test_rejects_missing_required_field(self, client, missing_field):
        payload = report_payload()
        del payload[missing_field]
        resp = client.post("/reports", json=payload)
        assert resp.status_code == 422

    def test_rejects_malformed_timestamp(self, client):
        payload = report_payload(timestamp="not-a-date")
        resp = client.post("/reports", json=payload)
        assert resp.status_code == 422

    def test_invalid_payload_does_not_persist_a_row(self, client, post_report):
        post_report(connectivity_status="bogus")
        assert client.get("/stations").json() == []

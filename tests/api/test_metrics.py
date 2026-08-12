"""Integration tests for GET /metrics/summary."""
import pytest

pytestmark = pytest.mark.api


class TestMetricsSummary:
    def test_empty_state_reports_zero_stations_and_null_average(self, client):
        resp = client.get("/metrics/summary")
        assert resp.status_code == 200
        assert resp.json() == {
            "total_stations": 0,
            "online_count": 0,
            "offline_count": 0,
            "flagged_count": 0,
            "average_latency_ms": None,
            "total_error_count": 0,
        }

    def test_aggregates_across_multiple_distinct_stations(self, client, post_report):
        post_report(station_id="STATION-A", connectivity_status="online", latency_ms=100, error_count=1)
        post_report(station_id="STATION-B", connectivity_status="offline", latency_ms=200, error_count=3)

        metrics = client.get("/metrics/summary").json()
        assert metrics["total_stations"] == 2
        assert metrics["online_count"] == 1
        assert metrics["offline_count"] == 1
        assert metrics["flagged_count"] == 1  # only STATION-B (offline) drops below 60
        assert metrics["average_latency_ms"] == 150.0
        assert metrics["total_error_count"] == 4

    def test_only_latest_report_per_station_counts_toward_aggregates(self, client, post_report):
        # Same station, two reports: an old bad one first, then a newer
        # good one. If the summary query were summing every report instead
        # of just the latest per station, total_stations and
        # total_error_count would both come out wrong here.
        post_report(
            station_id="STATION-A",
            timestamp="2024-06-01T10:00:00Z",
            connectivity_status="offline",
            error_count=10,
        )
        post_report(
            station_id="STATION-A",
            timestamp="2024-06-01T12:00:00Z",
            connectivity_status="online",
            error_count=0,
        )

        metrics = client.get("/metrics/summary").json()
        assert metrics["total_stations"] == 1
        assert metrics["offline_count"] == 0
        assert metrics["online_count"] == 1
        assert metrics["total_error_count"] == 0
        assert metrics["flagged_count"] == 0

    @pytest.mark.xfail(
        reason=(
            "Known defect: get_metrics_summary() shares the same "
            "MAX(timestamp)-equality-join as list_stations(). Two reports "
            "for one station with an identical latest timestamp double-count "
            "that station in total_stations, online/offline_count, and "
            "total_error_count. See test_stations.py for the isolated repro."
        ),
        strict=True,
    )
    def test_duplicate_latest_timestamp_does_not_double_count_a_station(self, client, post_report):
        tied_timestamp = "2024-06-01T10:00:00Z"
        post_report(station_id="STATION-A", timestamp=tied_timestamp, error_count=1)
        post_report(station_id="STATION-A", timestamp=tied_timestamp, error_count=1)

        metrics = client.get("/metrics/summary").json()
        assert metrics["total_stations"] == 1

"""Integration tests for GET /stations, /stations/{id}/status, /stations/poor-hygiene."""
import pytest

pytestmark = pytest.mark.api


class TestListStations:
    def test_empty_when_no_reports_ingested(self, client):
        assert client.get("/stations").json() == []

    def test_lists_latest_status_per_station(self, client, post_report):
        post_report(station_id="STATION-A", timestamp="2024-06-01T10:00:00Z")
        post_report(station_id="STATION-B", timestamp="2024-06-01T10:00:00Z")

        resp = client.get("/stations")
        assert resp.status_code == 200
        ids = {s["station_id"] for s in resp.json()}
        assert ids == {"STATION-A", "STATION-B"}

    def test_reflects_most_recent_report_when_health_changes(self, client, post_report):
        post_report(
            station_id="STATION-A",
            timestamp="2024-06-01T10:00:00Z",
            connectivity_status="online",
        )
        post_report(
            station_id="STATION-A",
            timestamp="2024-06-01T11:00:00Z",
            connectivity_status="offline",
        )

        [station] = client.get("/stations").json()
        assert station["connectivity_status"] == "offline"

    def test_uses_timestamp_not_insertion_order_to_determine_latest(self, client, post_report):
        # Deliberately insert the older report second. If the query picked
        # "latest" by insertion order (last row wins) instead of by
        # MAX(timestamp), this test would catch it -- it'd wrongly report
        # the station as online.
        post_report(
            station_id="STATION-A",
            timestamp="2024-06-01T11:00:00Z",
            connectivity_status="offline",
        )
        post_report(
            station_id="STATION-A",
            timestamp="2024-06-01T10:00:00Z",
            connectivity_status="online",
        )

        [station] = client.get("/stations").json()
        assert station["connectivity_status"] == "offline"

    @pytest.mark.xfail(
        reason=(
            "Known defect: list_stations() joins on "
            "StationReport.timestamp == MAX(timestamp) per station_id. When "
            "two reports for the same station share an identical timestamp, "
            "the equality join matches both rows and the station appears "
            "twice with different (conflicting) hygiene data. Fix requires "
            "a tiebreaker (e.g. ORDER BY timestamp DESC, id DESC LIMIT 1 per "
            "station) rather than a MAX-timestamp join."
        ),
        strict=True,
    )
    def test_station_appears_only_once_even_with_duplicate_latest_timestamps(
        self, client, post_report
    ):
        tied_timestamp = "2024-06-01T10:00:00Z"
        post_report(station_id="STATION-A", timestamp=tied_timestamp, connectivity_status="online")
        post_report(station_id="STATION-A", timestamp=tied_timestamp, connectivity_status="offline")

        stations = client.get("/stations").json()
        assert len(stations) == 1


class TestStationStatus:
    def test_returns_404_for_unknown_station(self, client):
        resp = client.get("/stations/DOES-NOT-EXIST/status")
        assert resp.status_code == 404
        assert "DOES-NOT-EXIST" in resp.json()["detail"]

    def test_returns_full_detail_for_known_station(self, client, post_report):
        post_report(
            station_id="STATION-A",
            latency_ms=100,
            error_count=1,
            firmware_version="v2.3.1",
        )

        resp = client.get("/stations/STATION-A/status")
        assert resp.status_code == 200
        body = resp.json()
        assert body["station_id"] == "STATION-A"
        assert body["latency_ms"] == 100
        assert body["error_count"] == 1
        assert body["firmware_version"] == "v2.3.1"
        assert body["hygiene_score"] == 90.0  # 100 - 5 (1 error) - 5 (100ms)

    def test_returns_most_recent_of_multiple_reports(self, client, post_report):
        post_report(station_id="STATION-A", timestamp="2024-06-01T10:00:00Z", error_count=0)
        post_report(station_id="STATION-A", timestamp="2024-06-01T12:00:00Z", error_count=5)

        body = client.get("/stations/STATION-A/status").json()
        assert body["error_count"] == 5


class TestPoorHygieneStations:
    def test_empty_when_no_stations_flagged(self, client, post_report):
        post_report(station_id="STATION-A", connectivity_status="online")
        assert client.get("/stations/poor-hygiene").json() == []

    def test_includes_only_flagged_stations(self, client, post_report):
        post_report(station_id="STATION-HEALTHY", connectivity_status="online")
        post_report(station_id="STATION-BAD", connectivity_status="offline", latency_ms=200, error_count=10)

        flagged = client.get("/stations/poor-hygiene").json()
        flagged_ids = {s["station_id"] for s in flagged}
        assert flagged_ids == {"STATION-BAD"}

    def test_recovered_station_drops_off_the_list(self, client, post_report):
        # A station that used to be unhealthy but has since recovered
        # shouldn't still show up here -- "poor-hygiene" means currently
        # flagged, based on the latest report, not "was ever flagged."
        post_report(
            station_id="STATION-A",
            timestamp="2024-06-01T10:00:00Z",
            connectivity_status="offline",
        )
        assert client.get("/stations/poor-hygiene").json() != []

        post_report(
            station_id="STATION-A",
            timestamp="2024-06-01T11:00:00Z",
            connectivity_status="online",
        )
        assert client.get("/stations/poor-hygiene").json() == []

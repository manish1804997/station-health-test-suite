"""Thin HTTP client for the e2e layer -- one method per endpoint.

Keeps the raw httpx/URL-building details out of the test bodies, the way
`tests/factories.py` keeps payload-building out of them. Only used here:
the unit/api/perf layers talk to the app in-process via FastAPI's
TestClient and have no need for this.
"""
import httpx


class StationHealthClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self._client = httpx.Client(base_url=base_url, timeout=timeout)

    def health(self) -> httpx.Response:
        return self._client.get("/health")

    def post_report(self, payload: dict) -> httpx.Response:
        return self._client.post("/reports", json=payload)

    def get_station_status(self, station_id: str) -> httpx.Response:
        return self._client.get(f"/stations/{station_id}/status")

    def get_metrics_summary(self) -> httpx.Response:
        return self._client.get("/metrics/summary")

    def close(self) -> None:
        self._client.close()

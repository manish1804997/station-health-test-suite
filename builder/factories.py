"""Test data builders.

Centralizing the "shape" of a valid health report here means every test that
needs one only specifies the fields it actually cares about, and a schema
change to ReportIn only requires updating this one place.
"""
from typing import Any

DEFAULT_TIMESTAMP = "2024-06-01T10:00:00Z"


def report_payload(**overrides: Any) -> dict:
    payload = {
        "station_id": "STATION-001",
        "timestamp": DEFAULT_TIMESTAMP,
        "connectivity_status": "online",
        "latency_ms": 50,
        "error_count": 0,
        "firmware_version": "v1.0.0",
    }
    payload.update(overrides)
    return payload

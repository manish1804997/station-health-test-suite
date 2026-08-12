"""E2E layer configuration -- currently just the target service URL.

Overridable via the E2E_BASE_URL environment variable, e.g. to point the
e2e suite at a stack running on a different host/port than the default
docker-compose setup. Mirrors how the service itself is configured
(DATABASE_URL, SIMULATED_LATENCY_MS as env vars with defaults).
"""
import os

SERVICE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")

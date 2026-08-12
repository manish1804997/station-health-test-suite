import os

# Has to happen before app.database/app.main get imported -- app.database
# builds its default engine from DATABASE_URL the moment it's imported, and
# we don't want that touching a real ./noc.db on disk. The client fixture
# below gives every test its own engine anyway, so this default barely
# matters in practice; it's just a safety net for a bare import.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SIMULATED_LATENCY_MS", "0")

import pytest
from app.database import Base, get_db
from app.main import app as fastapi_app
from factories import report_payload
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture()
def client(tmp_path):
    """A TestClient wired to a fresh, file-backed SQLite DB for this test only.

    Each test gets its own database file (via pytest's tmp_path) and its own
    engine/sessionmaker, injected through FastAPI's dependency override
    mechanism, so tests never share state or leak into a developer's local
    noc.db.
    """
    db_path = tmp_path / "test.db"
    engine = create_engine(
        f"sqlite:///{db_path}", connect_args={"check_same_thread": False}
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    fastapi_app.dependency_overrides[get_db] = override_get_db
    with TestClient(fastapi_app) as test_client:
        yield test_client

    fastapi_app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture()
def post_report(client):
    """Shorthand for ingesting a report with sensible defaults, overridable per test."""

    def _post(**overrides):
        return client.post("/reports", json=report_payload(**overrides))

    return _post

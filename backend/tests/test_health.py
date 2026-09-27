"""/health endpoint."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from newsalpha.api.app import create_app
from newsalpha.db.session import get_session


class _OkSession:
    def execute(self, *_: Any) -> None:
        return None


class _DownSession:
    def execute(self, *_: Any) -> None:
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))


def _client(session: object) -> TestClient:
    app = create_app()

    def override() -> Iterator[object]:
        yield session

    app.dependency_overrides[get_session] = override
    return TestClient(app)


def test_health_ok_when_database_answers() -> None:
    resp = _client(_OkSession()).get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"


def test_health_reports_degraded_when_database_down() -> None:
    resp = _client(_DownSession()).get("/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "degraded",
        "database": "unavailable",
        "version": resp.json()["version"],
    }


def test_openapi_schema_is_generated() -> None:
    resp = TestClient(create_app()).get("/openapi.json")
    assert resp.status_code == 200
    assert "/health" in resp.json()["paths"]


@pytest.mark.db
def test_health_against_real_postgres(live_db: None) -> None:
    resp = TestClient(create_app()).get("/health")
    assert resp.json()["database"] == "ok"

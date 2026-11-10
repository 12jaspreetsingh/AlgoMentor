from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.main import create_app


@pytest.fixture
def engine(monkeypatch):
    engine = MagicMock()
    monkeypatch.setattr("app.main.build_engine", lambda settings: engine)
    return engine


def test_liveness_and_docs_do_not_query_database(settings, engine):
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/v1/health/live").json() == {"status": "ok"}
        assert client.get("/docs").status_code == 200
        paths = client.get("/openapi.json").json()["paths"]
        assert set(paths) == {"/api/v1/health/live", "/api/v1/health/ready"}
        engine.connect.assert_not_called()
    engine.dispose.assert_called_once()


def test_readiness_reports_db_failure_without_leaking_details(settings, engine, caplog):
    engine.connect.side_effect = OperationalError("secret SQL", {}, Exception("private-password"))
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json() == {
        "status": "not_ready",
        "database": "unavailable",
        "schema_status": "unavailable",
    }
    assert "private-password" not in response.text + caplog.text
    assert "secret SQL" not in response.text + caplog.text


def test_readiness_rejects_old_revision(settings, engine):
    connection = engine.connect.return_value.__enter__.return_value
    connection.execute.return_value.scalars.return_value = ["old_revision"]
    with TestClient(create_app(settings)) as client:
        response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    assert response.json()["schema_status"] == "not_current"

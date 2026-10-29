import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from ci_analyzer.main import create_app


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="Requires a PostgreSQL test database"
)
def test_postgres_round_trip():
    with TestClient(create_app(os.environ["TEST_DATABASE_URL"])) as client:
        response = client.post("/api/builds", json={
            "name": f"Postgres integration {uuid4()}",
            "project": "integration-test",
            "log": "FAILED test_boot.py::test_boot - AssertionError\nFinished: FAILURE",
        })
        assert response.status_code == 201
        build = response.json()
        try:
            assert client.get(f"/api/builds/{build['id']}").json() == build
            assert client.get("/api/metrics").json()["categories"]["test"] >= 1
            assert client.get("/api/builds?project=integration-test").json()["total"] >= 1
        finally:
            assert client.delete(f"/api/builds/{build['id']}").status_code == 204
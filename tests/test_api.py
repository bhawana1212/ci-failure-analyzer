import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ci_analyzer.database import FailedTest
from ci_analyzer.main import create_app


@pytest.fixture
def client(tmp_path):
    application = create_app(f"sqlite:///{tmp_path / 'test.db'}")
    with TestClient(application) as test_client:
        yield test_client


def ingest(client, **changes):
    payload = {
        "name": "Build #142", "project": "firmware", "branch": "main",
        "log": "FAILED tests/test_boot.py::test_boot_sequence - AssertionError\nFinished: FAILURE",
    }
    payload.update(changes)
    return client.post("/api/builds", json=payload)


def test_ingest_list_detail_and_metrics(client):
    response = ingest(client)
    assert response.status_code == 201
    build = response.json()
    assert build["status"] == "failed"
    assert build["category"] == "test"
    assert "log" not in build
    assert client.get(f"/api/builds/{build['id']}").json() == build
    ingest(client, name="Build #143", log="Finished: SUCCESS")
    ingest(client, name="Build #144", log="Starting...")
    page = client.get("/api/builds?status=failed&search=firmware").json()
    assert page["total"] == 1
    assert "evidence" not in page["items"][0]
    metrics = client.get("/api/metrics").json()
    assert metrics["total"] == 3
    assert metrics["pass_rate"] == 50.0
    assert metrics["categories"] == {"test": 1, "unknown": 1}
    assert metrics["top_tests"][0]["count"] == 1
    assert metrics["projects"] == ["firmware"]


def test_upload(client):
    response = client.post(
        "/api/builds/upload", data={"name": "Build #145"},
        files={"file": ("console.log", b"\xef\xbb\xbfFinished: SUCCESS", "text/plain")},
    )
    assert response.status_code == 201
    assert response.json()["status"] == "passed"


@pytest.mark.parametrize("content", [b"", b"\xff", b"\x00text"])
def test_rejects_bad_upload(client, content):
    response = client.post(
        "/api/builds/upload", data={"name": "Build #1"},
        files={"file": ("console.log", content)},
    )
    assert response.status_code == 422


def test_upload_size_limit(client):
    response = client.post(
        "/api/builds/upload", data={"name": "Build #1"},
        files={"file": ("console.log", b"a" * (2 * 1024 * 1024 + 1))},
    )
    assert response.status_code == 413


@pytest.mark.parametrize("changes", [{"name": " "}, {"log": ""}, {"project": " "}])
def test_rejects_blank_fields(client, changes):
    assert ingest(client, **changes).status_code == 422


def test_pagination_filters_and_validation(client):
    ingest(client)
    ingest(client, name="Build #143", project="driver")
    assert client.get("/api/builds?limit=1&offset=1").json()["items"][0]["name"] == "Build #142"
    assert client.get("/api/builds?project=driver&category=test").json()["total"] == 1
    assert client.get("/api/builds?search=%25").json()["total"] == 0
    assert client.get("/api/builds?status=invalid").status_code == 422
    assert client.get("/api/builds?limit=0").status_code == 422
    assert client.get("/api/builds?offset=-1").status_code == 422


def test_delete_removes_tests(client):
    build_id = ingest(client).json()["id"]
    assert client.delete(f"/api/builds/{build_id}").status_code == 204
    assert client.get(f"/api/builds/{build_id}").status_code == 404
    assert client.delete(f"/api/builds/{build_id}").status_code == 404
    with Session(client.app.state.engine) as session:
        assert session.scalar(select(func.count()).select_from(FailedTest)) == 0
    assert client.get("/api/metrics").json()["total"] == 0


def test_empty_metrics_and_health(client):
    assert client.get("/api/metrics").json()["pass_rate"] is None
    assert client.get("/health").json() == {"status": "ok"}


def test_reopen_preserves_build(tmp_path):
    url = f"sqlite:///{tmp_path / 'persistent.db'}"
    with TestClient(create_app(url)) as first:
        ingest(first)
    with TestClient(create_app(url)) as second:
        assert second.get("/api/builds").json()["total"] == 1


def test_redacts_stored_evidence_and_metadata(client):
    result = ingest(client, name="token=secret", log="error: token=secret\nFinished: FAILURE")
    assert "secret" not in result.text
    assert "REDACTED" in result.text


def test_redacted_metadata_fits_database_columns(client):
    result = ingest(client, name="token=a " * 15)
    assert result.status_code == 201
    assert len(result.json()["name"]) <= 120


def test_dashboard_assets_and_samples(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "CI Failure Analyzer" in page.text
    for asset in ("app.js", "styles.css", "sample-builds.json"):
        assert client.get(f"/static/{asset}").status_code == 200
    for sample in client.get("/static/sample-builds.json").json():
        assert client.post("/api/builds", json=sample).status_code == 201
    assert client.get("/api/metrics").json()["total"] == 12
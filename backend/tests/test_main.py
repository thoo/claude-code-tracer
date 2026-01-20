from fastapi.testclient import TestClient

from claude_code_tracer.main import app

client = TestClient(app)


def test_read_root():
    """Test root endpoint returns 200 OK.

    Returns JSON in API-only mode, HTML when frontend build is present.
    """
    response = client.get("/")
    assert response.status_code == 200
    # Either JSON API response or HTML frontend
    content_type = response.headers.get("content-type", "")
    assert "application/json" in content_type or "text/html" in content_type


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

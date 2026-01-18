from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
from claude_code_tracer.main import app
from claude_code_tracer.models.responses import SessionSummary, TokenUsage
from datetime import datetime

client = TestClient(app)

def test_get_project_sessions():
    project_hash = "test-proj"
    session_id = "sess-1"

    mock_sessions = [
        {"session_id": session_id, "slug": "my-slug", "directory": "/tmp"}
    ]

    mock_summary = SessionSummary(
        session_id=session_id,
        start_time=datetime(2024, 1, 1),
        tokens=TokenUsage(),
        status="completed"
    )

    # Patch the async functions where they are imported in the router (Phase 4.2 refactoring)
    with patch("claude_code_tracer.routers.sessions.list_sessions_async", new_callable=AsyncMock, return_value=mock_sessions):
        with patch("claude_code_tracer.routers.sessions.parse_session_summary_async", new_callable=AsyncMock, return_value=mock_summary):
            response = client.get(f"/api/projects/{project_hash}/sessions")

            assert response.status_code == 200
            data = response.json()
            assert len(data["sessions"]) == 1
            assert data["sessions"][0]["session_id"] == session_id
            assert data["sessions"][0]["slug"] == "my-slug"

            # Verify the MOCK object was NOT modified (because the router made a copy)
            # This confirms the safety fix: the cached object (mock_summary) remains untouched.
            assert mock_summary.slug is None

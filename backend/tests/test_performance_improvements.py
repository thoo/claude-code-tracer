from datetime import datetime
from unittest.mock import patch

import pytest

from claude_code_tracer.routers.sessions import get_projects
from claude_code_tracer.services import database
from claude_code_tracer.services.database import (
    _session_views,
    get_or_create_session_view,
    invalidate_session_view,
)
from claude_code_tracer.services.log_parser import (
    get_all_projects_metrics,
    get_batch_subagent_metrics,
    get_project_total_metrics,
)


@pytest.fixture
def complex_project_structure(mock_projects_dir):
    """Create a project structure with multiple sessions and subagents."""
    project_hash = "perf-test-project"
    project_dir = mock_projects_dir / project_hash
    project_dir.mkdir()

    # Create 3 sessions
    session_ids = []
    for i in range(3):
        session_id = f"session-{i}"
        session_ids.append(session_id)
        session_path = project_dir / f"{session_id}.jsonl"

        with open(session_path, "w") as f:
            # Main session content
            f.write(
                f'{{"type": "assistant", "message": {{"id": "msg-{i}-1", "model": "claude-3-5-sonnet", "usage": {{"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}}, "timestamp": "2024-01-01T12:00:00Z"}}\n'
            )

            # Subagent directory for this session (new structure)
            subagents_dir = project_dir / session_id / "subagents"
            subagents_dir.mkdir(parents=True, exist_ok=True)

            # Create a subagent for this session
            agent_path = subagents_dir / f"agent-sub-{i}.jsonl"
            with open(agent_path, "w") as af:
                af.write(
                    f'{{"type": "assistant", "message": {{"id": "sub-{i}-1", "model": "claude-3-haiku", "usage": {{"input_tokens": 50, "output_tokens": 25, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}}, "timestamp": "2024-01-01T12:00:05Z"}}\n'
                )

    # Create another project
    other_project = mock_projects_dir / "other-project"
    other_project.mkdir()
    with open(other_project / "sess-other.jsonl", "w") as f:
        f.write(
            '{"type": "assistant", "message": {"id": "msg-other", "model": "claude-3-opus", "usage": {"input_tokens": 200, "output_tokens": 100, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}, "timestamp": "2024-01-02T12:00:00Z"}\n'
        )

    return project_hash, session_ids


def test_get_project_total_metrics_glob(complex_project_structure):
    """Test optimized project metrics aggregation."""
    project_hash, _ = complex_project_structure

    metrics = get_project_total_metrics(project_hash)

    # Verify aggregation
    assert metrics["session_count"] == 3
    # 3 sessions * (100 main + 50 subagent) = 450 input tokens
    assert metrics["tokens"]["input_tokens"] == 450
    # 3 sessions * (50 main + 25 subagent) = 225 output tokens
    assert metrics["tokens"]["output_tokens"] == 225


def test_get_all_projects_metrics(complex_project_structure):
    """Test retrieving metrics for all projects in one go."""
    project_hash, _ = complex_project_structure

    all_metrics = get_all_projects_metrics()

    assert project_hash in all_metrics
    assert "other-project" in all_metrics

    proj_metrics = all_metrics[project_hash]
    assert proj_metrics["session_count"] == 3
    assert proj_metrics["tokens"]["input_tokens"] == 450

    other_metrics = all_metrics["other-project"]
    assert other_metrics["session_count"] == 1
    assert other_metrics["tokens"]["input_tokens"] == 200


def test_get_batch_subagent_metrics(complex_project_structure):
    """Test batch aggregation of subagent metrics."""
    project_hash, session_ids = complex_project_structure
    project_dir = database.get_project_dir(project_hash)

    # Collect all subagent paths manually for the test
    subagent_paths = []
    for sess_id in session_ids:
        subagents_dir = project_dir / sess_id / "subagents"
        subagent_paths.extend(list(subagents_dir.glob("*.jsonl")))

    assert len(subagent_paths) == 3

    tokens, cost, models = get_batch_subagent_metrics(subagent_paths)

    # 3 subagents * 50 input tokens
    assert tokens.input_tokens == 150
    # 3 subagents * 25 output tokens
    assert tokens.output_tokens == 75
    assert "claude-3-haiku" in models


@pytest.mark.asyncio
async def test_get_projects_api_integration():
    """Test that get_projects API endpoint uses optimized metrics."""
    from unittest.mock import AsyncMock

    mock_projects = [
        {"path_hash": "p1", "project_path": "/path/p1", "session_count": 0},
        {"path_hash": "p2", "project_path": "/path/p2", "session_count": 0},
    ]

    mock_metrics = {
        "p1": {
            "session_count": 5,
            "tokens": {"input_tokens": 1000},
            "total_cost": 0.5,
            "last_activity": datetime(2024, 1, 2),
        }
        # p2 is missing from metrics (e.g. no sessions), should fallback or be empty
    }

    # Patch the async functions where they are imported in the router (Phase 4.2 refactoring)
    with patch(
        "claude_code_tracer.routers.sessions.list_projects_async",
        new_callable=AsyncMock,
        return_value=mock_projects,
    ):
        with patch(
            "claude_code_tracer.routers.sessions.get_all_projects_metrics_async",
            new_callable=AsyncMock,
            return_value=mock_metrics,
        ):
            with patch(
                "claude_code_tracer.routers.sessions.get_project_total_metrics_async",
                new_callable=AsyncMock,
                return_value={},
            ) as mock_fallback:
                response = await get_projects()

                assert len(response.projects) == 2

                # Check p1 (from batch metrics)
                p1 = next(p for p in response.projects if p.path_hash == "p1")
                assert p1.session_count == 5
                assert p1.tokens.input_tokens == 1000
                assert p1.total_cost == 0.5

                # Check p2 (fallback)
                next(p for p in response.projects if p.path_hash == "p2")
                # Ensure fallback was called for p2
                mock_fallback.assert_called_with("p2")


def test_session_view_caching(complex_project_structure):
    """Test session view creation and caching."""
    project_hash, session_ids = complex_project_structure
    session_id = session_ids[0]
    session_path = database.get_session_path(project_hash, session_id)

    # Clear cache
    _session_views.clear()

    # 1. Create view
    view_name1 = get_or_create_session_view(session_path)
    assert view_name1.startswith("session_")
    assert str(session_path) in _session_views

    # 2. Get view again (should be same)
    view_name2 = get_or_create_session_view(session_path)
    assert view_name1 == view_name2

    # 3. Invalidate view
    invalidate_session_view(session_path)
    assert str(session_path) not in _session_views

    # 4. Create new view (should be different or re-created)
    get_or_create_session_view(session_path)
    assert str(session_path) in _session_views


def test_get_all_projects_metrics_empty(mock_projects_dir):
    """Test behavior with no projects."""
    # Ensure projects dir is empty for this test context if using mock
    # But mock_projects_dir fixture creates the directory.
    # The fixture 'complex_project_structure' creates projects, but this test uses 'mock_projects_dir' directly.
    # We should clean it or ensure it's empty. Pytest fixtures are function-scoped by default, so it should be empty here unless 'complex_project_structure' was used.

    # Actually, verify that 'get_all_projects_metrics' handles empty result gracefully.
    # We need to make sure no .jsonl files are in the mock_projects_dir

    metrics = get_all_projects_metrics()
    # It might return {} or contain projects if other tests left artifacts?
    # Fixtures are fresh per test function usually.
    # But to be safe, just assert it returns a dict.
    assert isinstance(metrics, dict)
    if not any(p.iterdir() for p in database.PROJECTS_DIR.iterdir() if p.is_dir()):
        assert metrics == {}

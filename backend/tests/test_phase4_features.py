"""Tests for Phase 4 features: Background Index, Persistent Cache, Async I/O, Datetime Standardization."""

import json
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from claude_code_tracer.services.cache import (
    PersistentCache,
    SessionAggregateMetrics,
)
from claude_code_tracer.services.index import (
    GlobalIndex,
    ProjectIndex,
    SessionMetadata,
    get_projects_from_index,
    get_sessions_from_index,
)
from claude_code_tracer.utils.datetime import normalize_datetime, now_utc, parse_timestamp

# ============================================================================
# Tests for utils/datetime.py (Priority 4.5)
# ============================================================================


class TestNormalizeDatetime:
    """Tests for normalize_datetime function."""

    def test_none_returns_min_datetime_with_utc(self):
        """None should return datetime.min with UTC timezone."""
        result = normalize_datetime(None)
        assert result == datetime.min.replace(tzinfo=UTC)
        assert result.tzinfo == UTC

    def test_naive_datetime_becomes_utc(self):
        """Naive datetime should be assumed UTC."""
        naive = datetime(2024, 6, 15, 12, 30, 45)
        result = normalize_datetime(naive)
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)
        assert result.tzinfo == UTC

    def test_aware_datetime_converted_to_utc(self):
        """Aware datetime should be converted to UTC."""
        # Create a datetime with +05:00 offset
        offset = timezone(timedelta(hours=5))
        aware = datetime(2024, 6, 15, 17, 30, 45, tzinfo=offset)
        result = normalize_datetime(aware)
        # 17:30 at +05:00 is 12:30 UTC
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)
        assert result.tzinfo == UTC

    def test_utc_datetime_unchanged(self):
        """UTC datetime should remain unchanged."""
        utc_dt = datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)
        result = normalize_datetime(utc_dt)
        assert result == utc_dt

    def test_iso_string_with_z_suffix(self):
        """ISO string with Z suffix should be parsed correctly."""
        result = normalize_datetime("2024-06-15T12:30:45Z")
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)

    def test_iso_string_with_offset(self):
        """ISO string with offset should be parsed and converted to UTC."""
        result = normalize_datetime("2024-06-15T17:30:45+05:00")
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)

    def test_invalid_string_returns_min_datetime(self):
        """Invalid string should return datetime.min with UTC."""
        result = normalize_datetime("not-a-date")
        assert result == datetime.min.replace(tzinfo=UTC)

    def test_empty_string_returns_min_datetime(self):
        """Empty string should return datetime.min with UTC."""
        result = normalize_datetime("")
        assert result == datetime.min.replace(tzinfo=UTC)


class TestParseTimestamp:
    """Tests for parse_timestamp function."""

    def test_none_returns_none(self):
        """None should return None."""
        assert parse_timestamp(None) is None

    def test_naive_datetime_becomes_utc(self):
        """Naive datetime should become UTC-aware."""
        naive = datetime(2024, 6, 15, 12, 30, 45)
        result = parse_timestamp(naive)
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)

    def test_aware_datetime_converted_to_utc(self):
        """Aware datetime should be converted to UTC."""
        offset = timezone(timedelta(hours=-3))
        aware = datetime(2024, 6, 15, 9, 30, 45, tzinfo=offset)
        result = parse_timestamp(aware)
        # 09:30 at -03:00 is 12:30 UTC
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)

    def test_iso_string_with_z(self):
        """ISO string with Z should be parsed correctly."""
        result = parse_timestamp("2024-06-15T12:30:45Z")
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)

    def test_iso_string_with_offset(self):
        """ISO string with offset should be parsed and converted."""
        result = parse_timestamp("2024-06-15T12:30:45+00:00")
        assert result == datetime(2024, 6, 15, 12, 30, 45, tzinfo=UTC)

    def test_invalid_string_returns_none(self):
        """Invalid string should return None."""
        assert parse_timestamp("invalid") is None

    def test_malformed_iso_returns_none(self):
        """Malformed ISO string should return None."""
        assert parse_timestamp("2024-13-45T99:99:99") is None


class TestNowUtc:
    """Tests for now_utc function."""

    def test_returns_utc_aware_datetime(self):
        """Should return a UTC-aware datetime."""
        result = now_utc()
        assert result.tzinfo == UTC

    def test_returns_current_time(self):
        """Should return approximately current time."""
        before = datetime.now(UTC)
        result = now_utc()
        after = datetime.now(UTC)
        assert before <= result <= after


# ============================================================================
# Tests for services/index.py (Priority 4.1)
# ============================================================================


class TestSessionMetadata:
    """Tests for SessionMetadata dataclass."""

    def test_default_values(self):
        """Test default values for SessionMetadata."""
        meta = SessionMetadata(session_id="test-123")
        assert meta.session_id == "test-123"
        assert meta.slug is None
        assert meta.directory is None
        assert meta.file_path is None
        assert meta.file_mtime == 0.0
        assert meta.start_time is None


class TestProjectIndex:
    """Tests for ProjectIndex dataclass."""

    def test_default_values(self):
        """Test default values for ProjectIndex."""
        idx = ProjectIndex(path_hash="hash123")
        assert idx.path_hash == "hash123"
        assert idx.project_path == "Unknown"
        assert idx.sessions == {}
        assert idx.last_scanned == 0.0


class TestGlobalIndex:
    """Tests for GlobalIndex singleton."""

    def test_singleton_pattern(self):
        """GlobalIndex should be a singleton."""
        # Reset singleton for test isolation
        GlobalIndex._instance = None

        idx1 = GlobalIndex()
        idx2 = GlobalIndex()
        assert idx1 is idx2

    def test_initial_state(self):
        """Test initial state of GlobalIndex."""
        GlobalIndex._instance = None
        idx = GlobalIndex()
        assert idx.is_initialized is False
        assert idx.projects == {}

    def test_get_project_returns_none_for_missing(self):
        """get_project should return None for missing project."""
        GlobalIndex._instance = None
        idx = GlobalIndex()
        assert idx.get_project("nonexistent") is None

    def test_get_sessions_returns_empty_for_missing(self):
        """get_sessions should return empty list for missing project."""
        GlobalIndex._instance = None
        idx = GlobalIndex()
        assert idx.get_sessions("nonexistent") == []


@pytest.fixture
def mock_projects_dir(tmp_path):
    """Create a mock projects directory structure."""
    projects_dir = tmp_path / ".claude" / "projects"
    projects_dir.mkdir(parents=True)

    # Create a project with sessions-index.json
    proj1 = projects_dir / "project-hash-1"
    proj1.mkdir()

    index_data = {
        "entries": [
            {
                "sessionId": "11111111-1111-1111-1111-111111111111",
                "slug": "test-session",
                "projectPath": "/path/to/project",
            }
        ]
    }
    (proj1 / "sessions-index.json").write_text(json.dumps(index_data))

    # Create a session file
    session_file = proj1 / "11111111-1111-1111-1111-111111111111.jsonl"
    session_file.write_text('{"type": "user", "cwd": "/path/to/project"}\n')

    # Create a project without index (filesystem-only)
    proj2 = projects_dir / "project-hash-2"
    proj2.mkdir()
    # Use valid UUID for session filename
    session2 = proj2 / "22222222-2222-2222-2222-222222222222.jsonl"
    session2.write_text('{"type": "user", "cwd": "/another/path"}\n')

    return projects_dir


def test_scan_projects_populates_index(mock_projects_dir):
    """Test that scan_projects populates the index correctly."""
    GlobalIndex._instance = None

    with patch("claude_code_tracer.services.index.PROJECTS_DIR", mock_projects_dir):
        idx = GlobalIndex()
        idx.scan_projects()

        assert idx.is_initialized is True
        assert len(idx.projects) == 2

        # Check project from index
        proj1 = idx.get_project("project-hash-1")
        assert proj1 is not None
        assert proj1.project_path == "/path/to/project"
        assert "11111111-1111-1111-1111-111111111111" in proj1.sessions

        # Check project from filesystem scan
        proj2 = idx.get_project("project-hash-2")
        assert proj2 is not None
        assert "22222222-2222-2222-2222-222222222222" in proj2.sessions


def test_get_projects_from_index_fallback():
    """Test that get_projects_from_index falls back when not initialized."""
    GlobalIndex._instance = None
    idx = GlobalIndex()
    idx._initialized = False

    # Patch the imported function in database module
    with patch("claude_code_tracer.services.database.list_projects") as mock_list:
        mock_list.return_value = [
            {"path_hash": "test", "project_path": "/test", "session_count": 0}
        ]
        get_projects_from_index()
        mock_list.assert_called_once()


def test_get_sessions_from_index_fallback():
    """Test that get_sessions_from_index falls back when not initialized."""
    GlobalIndex._instance = None
    idx = GlobalIndex()
    idx._initialized = False

    # Patch the imported function in database module
    with patch("claude_code_tracer.services.database.list_sessions") as mock_list:
        mock_list.return_value = [{"session_id": "test", "slug": None, "directory": ""}]
        get_sessions_from_index("test-hash")
        mock_list.assert_called_once_with("test-hash")


# ============================================================================
# Tests for services/cache.py - PersistentCache (Priority 4.3)
# ============================================================================


class TestSessionAggregateMetrics:
    """Tests for SessionAggregateMetrics dataclass."""

    def test_default_values(self):
        """Test default values."""
        metrics = SessionAggregateMetrics(session_id="test-session", status="completed")
        assert metrics.session_id == "test-session"
        assert metrics.status == "completed"
        assert metrics.input_tokens == 0
        assert metrics.output_tokens == 0
        assert metrics.total_cost == 0.0
        assert metrics.mtime == 0.0


class TestPersistentCache:
    """Tests for PersistentCache singleton."""

    @pytest.fixture(autouse=True)
    def reset_singleton(self):
        """Reset singleton before each test."""
        PersistentCache._instance = None
        yield
        PersistentCache._instance = None

    def test_singleton_pattern(self):
        """PersistentCache should be a singleton."""
        cache1 = PersistentCache()
        cache2 = PersistentCache()
        assert cache1 is cache2

    def test_set_and_get_session_metrics(self):
        """Test storing and retrieving session metrics."""
        cache = PersistentCache()

        metrics = SessionAggregateMetrics(
            session_id="session-1",
            status="completed",
            input_tokens=1000,
            output_tokens=500,
            total_cost=0.05,
            mtime=12345.0,
        )

        cache.set_session_metrics("project-1", metrics)

        # Retrieve with matching mtime
        retrieved = cache.get_session_metrics("project-1", "session-1", 12345.0)
        assert retrieved is not None
        assert retrieved.input_tokens == 1000
        assert retrieved.total_cost == 0.05

    def test_get_session_metrics_returns_none_for_mtime_mismatch(self):
        """Cache should return None if mtime doesn't match."""
        cache = PersistentCache()

        metrics = SessionAggregateMetrics(session_id="session-1", status="completed", mtime=12345.0)
        cache.set_session_metrics("project-1", metrics)

        # Different mtime should return None
        result = cache.get_session_metrics("project-1", "session-1", 99999.0)
        assert result is None

    def test_get_session_metrics_returns_none_for_non_completed(self):
        """Cache should return None for non-completed sessions."""
        cache = PersistentCache()

        metrics = SessionAggregateMetrics(
            session_id="session-1",
            status="running",  # Not completed
            mtime=12345.0,
        )
        cache.set_session_metrics("project-1", metrics)

        result = cache.get_session_metrics("project-1", "session-1", 12345.0)
        assert result is None

    def test_get_project_cached_totals(self):
        """Test aggregating totals for a project."""
        cache = PersistentCache()

        # Add multiple completed sessions
        for i in range(3):
            metrics = SessionAggregateMetrics(
                session_id=f"session-{i}",
                status="completed",
                input_tokens=100,
                output_tokens=50,
                total_cost=0.01,
                mtime=12345.0,
            )
            cache.set_session_metrics("project-1", metrics)

        totals, cached_ids = cache.get_project_cached_totals("project-1")

        assert totals["input_tokens"] == 300
        assert totals["output_tokens"] == 150
        assert totals["total_cost"] == pytest.approx(0.03)
        assert len(cached_ids) == 3

    def test_get_project_cached_totals_excludes_non_completed(self):
        """Totals should exclude non-completed sessions."""
        cache = PersistentCache()

        # Add one completed and one running session
        cache.set_session_metrics(
            "project-1",
            SessionAggregateMetrics(
                session_id="completed-1", status="completed", input_tokens=100, mtime=12345.0
            ),
        )
        cache.set_session_metrics(
            "project-1",
            SessionAggregateMetrics(
                session_id="running-1", status="running", input_tokens=500, mtime=12345.0
            ),
        )

        totals, cached_ids = cache.get_project_cached_totals("project-1")

        assert totals["input_tokens"] == 100  # Only from completed
        assert "completed-1" in cached_ids
        assert "running-1" not in cached_ids

    def test_invalidate_session(self):
        """Test invalidating a specific session."""
        cache = PersistentCache()

        cache.set_session_metrics(
            "project-1",
            SessionAggregateMetrics(session_id="session-1", status="completed", mtime=12345.0),
        )

        # Verify it exists
        assert cache.get_session_metrics("project-1", "session-1", 12345.0) is not None

        # Invalidate
        cache.invalidate_session("project-1", "session-1")

        # Verify it's gone
        assert cache.get_session_metrics("project-1", "session-1", 12345.0) is None

    def test_invalidate_project(self):
        """Test invalidating all sessions for a project."""
        cache = PersistentCache()

        cache.set_session_metrics(
            "project-1",
            SessionAggregateMetrics(session_id="session-1", status="completed", mtime=12345.0),
        )
        cache.set_session_metrics(
            "project-1",
            SessionAggregateMetrics(session_id="session-2", status="completed", mtime=12345.0),
        )

        cache.invalidate_project("project-1")

        assert cache.get_session_metrics("project-1", "session-1", 12345.0) is None
        assert cache.get_session_metrics("project-1", "session-2", 12345.0) is None

    def test_clear(self):
        """Test clearing all cached data."""
        cache = PersistentCache()

        cache.set_session_metrics(
            "project-1",
            SessionAggregateMetrics(session_id="session-1", status="completed", mtime=12345.0),
        )

        cache.clear()

        totals, ids = cache.get_project_cached_totals("project-1")
        assert totals == {}
        assert ids == set()


def test_persistent_cache_save_and_load(tmp_path):
    """Test saving and loading cache from disk."""
    cache_file = tmp_path / "tracer-cache.json"

    with patch("claude_code_tracer.services.cache.CACHE_FILE", cache_file):
        with patch("claude_code_tracer.services.cache.CLAUDE_DIR", tmp_path):
            # Reset singleton
            PersistentCache._instance = None

            # Create cache and add data
            cache = PersistentCache()
            cache.set_session_metrics(
                "project-1",
                SessionAggregateMetrics(
                    session_id="session-1",
                    status="completed",
                    input_tokens=1000,
                    total_cost=0.05,
                    mtime=12345.0,
                ),
            )

            # Save to disk
            cache.save()
            assert cache_file.exists()

            # Reset singleton and load from disk
            PersistentCache._instance = None
            cache2 = PersistentCache()

            # Verify data was loaded
            metrics = cache2.get_session_metrics("project-1", "session-1", 12345.0)
            assert metrics is not None
            assert metrics.input_tokens == 1000
            assert metrics.total_cost == 0.05


# ============================================================================
# Tests for services/async_io.py (Priority 4.2)
# ============================================================================


@pytest.mark.asyncio
async def test_list_projects_async_uses_index_when_initialized():
    """list_projects_async should use index when initialized."""
    GlobalIndex._instance = None
    idx = GlobalIndex()
    idx._initialized = True
    idx._projects = {"hash1": ProjectIndex(path_hash="hash1", project_path="/path1")}

    from claude_code_tracer.services.async_io import list_projects_async

    with patch("claude_code_tracer.services.async_io.get_global_index", return_value=idx):
        with patch("claude_code_tracer.services.async_io.get_projects_from_index") as mock_get:
            mock_get.return_value = [{"path_hash": "hash1", "project_path": "/path1"}]
            await list_projects_async()
            mock_get.assert_called_once()


@pytest.mark.asyncio
async def test_list_projects_async_falls_back_when_not_initialized():
    """list_projects_async should fall back to sync function when not initialized."""
    GlobalIndex._instance = None
    idx = GlobalIndex()
    idx._initialized = False

    from claude_code_tracer.services.async_io import list_projects_async

    with patch("claude_code_tracer.services.async_io.get_global_index", return_value=idx):
        with patch("claude_code_tracer.services.async_io.sync_list_projects") as mock_sync:
            mock_sync.return_value = [{"path_hash": "test"}]
            await list_projects_async()
            # sync function is called via asyncio.to_thread
            mock_sync.assert_called_once()


@pytest.mark.asyncio
async def test_list_sessions_async_uses_index_when_initialized():
    """list_sessions_async should use index when initialized."""
    GlobalIndex._instance = None
    idx = GlobalIndex()
    idx._initialized = True

    from claude_code_tracer.services.async_io import list_sessions_async

    with patch("claude_code_tracer.services.async_io.get_global_index", return_value=idx):
        with patch("claude_code_tracer.services.async_io.get_sessions_from_index") as mock_get:
            mock_get.return_value = [{"session_id": "sess1"}]
            await list_sessions_async("hash1")
            mock_get.assert_called_once_with("hash1")


@pytest.mark.asyncio
async def test_parse_session_summary_async():
    """Test async wrapper for parse_session_summary."""
    from claude_code_tracer.models.responses import SessionSummary, TokenUsage
    from claude_code_tracer.services.async_io import parse_session_summary_async

    mock_summary = SessionSummary(
        session_id="test", status="completed", tokens=TokenUsage(), start_time=now_utc()
    )

    with patch(
        "claude_code_tracer.services.async_io.sync_parse_session_summary", return_value=mock_summary
    ):
        result = await parse_session_summary_async("proj", "sess")
        assert result == mock_summary


@pytest.mark.asyncio
async def test_get_session_tool_usage_async():
    """Test async wrapper for get_session_tool_usage."""
    from claude_code_tracer.models.responses import ToolUsageResponse
    from claude_code_tracer.services.async_io import get_session_tool_usage_async

    mock_response = ToolUsageResponse(tools=[], total_calls=0)

    with patch(
        "claude_code_tracer.services.async_io.sync_get_session_tool_usage",
        return_value=mock_response,
    ):
        result = await get_session_tool_usage_async("proj", "sess")
        assert result == mock_response


@pytest.mark.asyncio
async def test_check_session_exists_async(tmp_path):
    """Test async wrapper for checking session existence."""
    from claude_code_tracer.services.async_io import check_session_exists_async

    # Create a mock session file
    session_file = tmp_path / "session.jsonl"
    session_file.touch()

    with patch("claude_code_tracer.services.async_io.get_session_path", return_value=session_file):
        assert await check_session_exists_async("proj", "sess") is True

    with patch(
        "claude_code_tracer.services.async_io.get_session_path",
        return_value=tmp_path / "nonexistent.jsonl",
    ):
        assert await check_session_exists_async("proj", "sess") is False


@pytest.mark.asyncio
async def test_get_file_mtime_async(tmp_path):
    """Test async wrapper for getting file mtime."""
    from claude_code_tracer.services.async_io import get_file_mtime_async

    # Create a file
    test_file = tmp_path / "test.txt"
    test_file.touch()

    mtime = await get_file_mtime_async(test_file)
    assert mtime > 0

    # Non-existent file should return 0
    mtime = await get_file_mtime_async(tmp_path / "nonexistent.txt")
    assert mtime == 0.0


@pytest.mark.asyncio
async def test_save_persistent_cache_async():
    """Test async wrapper for saving persistent cache."""
    from claude_code_tracer.services.async_io import save_persistent_cache_async

    mock_cache = MagicMock()

    with patch(
        "claude_code_tracer.services.async_io.get_persistent_cache", return_value=mock_cache
    ):
        await save_persistent_cache_async()
        mock_cache.save.assert_called_once()


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.asyncio
async def test_background_scanner_lifecycle():
    """Test starting and stopping the background scanner."""
    GlobalIndex._instance = None

    with patch("claude_code_tracer.services.index.PROJECTS_DIR") as mock_dir:
        mock_dir.exists.return_value = True
        mock_dir.iterdir.return_value = []

        idx = GlobalIndex()

        # Start scanner
        await idx.start_background_scanner()
        assert idx._background_task is not None
        assert idx.is_initialized is True

        # Stop scanner
        await idx.stop_background_scanner()
        assert idx._background_task is None

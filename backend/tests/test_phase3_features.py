import pytest
from pathlib import Path
from datetime import datetime, timedelta
import base64
import time
import json
from unittest.mock import patch, MagicMock

from claude_code_tracer.routers.sessions import (
    get_session_messages,
    encode_cursor,
    decode_cursor,
    get_session_tools,
    get_session_metrics_endpoint,
    get_session_subagents_endpoint,
    get_session_message_filters,
)
from claude_code_tracer.services import database
from claude_code_tracer.services.cache import (
    clear_all_caches,
    get_cache_stats,
    _cached_tool_usage,
)
from claude_code_tracer.models.responses import (
    ToolUsageResponse, 
    ToolUsageStats,
    SessionMetricsResponse,
    TokenUsage,
    CostBreakdown,
    SubagentListResponse,
    MessageFilterOptions,
    MessageListResponse
)

# --- Fixtures ---

@pytest.fixture
def large_session_file(mock_projects_dir):
    """Create a session file with enough messages for pagination."""
    project_hash = "pagination-project"
    project_dir = mock_projects_dir / project_hash
    project_dir.mkdir(exist_ok=True)
    
    session_id = "pagination-session"
    session_path = project_dir / f"{session_id}.jsonl"
    
    start_time = datetime(2024, 1, 1, 12, 0, 0)
    
    with open(session_path, "w") as f:
        for i in range(100):
            timestamp = (start_time + timedelta(seconds=i)).isoformat() + "Z"
            # Create a mix of user and assistant messages
            msg_type = "user" if i % 2 == 0 else "assistant"
            content = f"Message {i}"
            
            # Simple message structure
            msg = {
                "uuid": f"msg-{i}",
                "type": msg_type,
                "sessionId": session_id,
                "data": None,
                "toolUseID": None,
                "parentToolUseID": None,
                "message": {
                    "id": f"msg-{i}",
                    # DuckDB CAST(LIST AS VARCHAR) produces non-JSON (single quotes), so we store as string
                    "content": json.dumps([{"type": "text", "text": content}]),
                    "model": "claude-3-sonnet" if msg_type == "assistant" else None,
                    "usage": {"input_tokens": 10, "output_tokens": 10} if msg_type == "assistant" else None
                },
                "timestamp": timestamp
            }
            # For user messages, content is a list of blocks too in our structure usually, 
            # or just simple structure. Let's keep it consistent with what parser expects.
            
            # Write line
            f.write(json.dumps(msg) + "\n")
            
    return project_hash, session_id, session_path

@pytest.fixture
def cache_test_session(mock_projects_dir):
    """Create a session for testing caching."""
    project_hash = "cache-project"
    project_dir = mock_projects_dir / project_hash
    project_dir.mkdir(exist_ok=True)

    session_id = "cache-session"
    session_path = project_dir / f"{session_id}.jsonl"

    with open(session_path, "w") as f:
        # Include uuid field which is required for session_has_messages validation
        f.write('{"type": "user", "uuid": "test-uuid-1", "message": {"id": "1", "content": "hi"}, "timestamp": "2024-01-01T12:00:00Z"}\n')

    return project_hash, session_id, session_path

# --- Tests for Cursor Utilities ---

def test_cursor_encoding_decoding():
    ts = datetime(2024, 1, 1, 12, 0, 0)
    uuid = "msg-123"
    
    encoded = encode_cursor(ts, uuid)
    assert isinstance(encoded, str)
    
    decoded_ts, decoded_uuid = decode_cursor(encoded)
    assert decoded_uuid == uuid
    assert decoded_ts == ts

def test_invalid_cursor():
    ts, uuid = decode_cursor("invalid-base64")
    assert ts is None
    assert uuid is None
    
    ts, uuid = decode_cursor(base64.urlsafe_b64encode(b"not|enough|parts").decode())
    assert ts is None  # Should fail timestamp parsing or split check depending on implementation details
    # Actually split(..., 1) will return 2 parts if there are 2 pipes, but timestamp parsing might fail.
    # The current implementation expects 2 parts: ts|uuid. "not|enough|parts" has 3 parts if split by |, 
    # but split(..., 1) stops at first pipe. So "not" and "enough|parts". 
    # "not" is not a valid iso timestamp.

from fastapi.testclient import TestClient
from claude_code_tracer.main import app

client = TestClient(app)

# ... (rest of imports)

# --- Tests for Keyset Pagination (Priority 3.1 & 3.2) ---

def test_keyset_pagination_flow(large_session_file):
    """Test full flow of keyset pagination."""
    project_hash, session_id, _ = large_session_file
    
    # 1. Fetch first page (limit 10)
    response1 = client.get(
        f"/api/sessions/{project_hash}/{session_id}/messages",
        params={"per_page": 10}
    )
    if response1.status_code != 200:
        print(f"Error response: {response1.text}")
    assert response1.status_code == 200
    page1 = MessageListResponse(**response1.json())
    
    assert len(page1.messages) == 10
    assert page1.has_more is True
    assert page1.next_cursor is not None
    assert page1.messages[0].uuid == "msg-0"
    assert page1.messages[-1].uuid == "msg-9"
    
    # 2. Fetch second page using cursor
    response2 = client.get(
        f"/api/sessions/{project_hash}/{session_id}/messages",
        params={"per_page": 10, "cursor": page1.next_cursor}
    )
    assert response2.status_code == 200
    page2 = MessageListResponse(**response2.json())
    
    assert len(page2.messages) == 10
    assert page2.has_more is True
    assert page2.next_cursor is not None
    # Should start after msg-9
    assert page2.messages[0].uuid == "msg-10"
    assert page2.messages[-1].uuid == "msg-19"
    
    # 3. Verify total is 0 in cursor mode (Lazy Counting)
    assert page2.total == 0
    assert page2.total_pages == 0

def test_end_of_pagination(large_session_file):
    """Test reaching the end of results."""
    project_hash, session_id, _ = large_session_file
    
    # Skip to near the end (msg-90 to msg-99)
    # Construct a cursor manually for msg-89
    ts = datetime(2024, 1, 1, 12, 0, 0) + timedelta(seconds=89)
    cursor = encode_cursor(ts, "msg-89")
    
    response = client.get(
        f"/api/sessions/{project_hash}/{session_id}/messages",
        params={"per_page": 20, "cursor": cursor}
    )
    if response.status_code != 200:
        print(f"Error response end: {response.text}")
    assert response.status_code == 200
    last_page = MessageListResponse(**response.json())
    
    assert len(last_page.messages) == 10 # Should get 90-99
    assert last_page.has_more is False
    assert last_page.next_cursor is None
    assert last_page.messages[0].uuid == "msg-90"
    assert last_page.messages[-1].uuid == "msg-99"

# --- Tests for Query Result Caching (Priority 3.6) ---

@pytest.mark.asyncio
async def test_tool_usage_caching(cache_test_session):
    """Test that tool usage results are cached and invalidated on file change."""
    from unittest.mock import AsyncMock

    project_hash, session_id, session_path = cache_test_session
    clear_all_caches()

    mock_response = ToolUsageResponse(tools=[ToolUsageStats(name="test", count=1)], total_calls=1)

    # Patch the async service function where it is imported in the router (Phase 4.2 refactoring)
    with patch("claude_code_tracer.routers.sessions.get_session_tool_usage_async", new_callable=AsyncMock, return_value=mock_response) as mock_query:

        # 1. First call - should query
        resp1 = await get_session_tools(project_hash, session_id)
        assert mock_query.call_count == 1
        assert resp1 == mock_response

        # 2. Second call - should use cache
        resp2 = await get_session_tools(project_hash, session_id)
        assert mock_query.call_count == 1  # Count shouldn't increase
        assert resp2 == mock_response

        # 3. Touch file to change mtime
        time.sleep(0.01)  # Ensure mtime changes
        session_path.touch()

        # 4. Third call - should re-query due to mtime change
        resp3 = await get_session_tools(project_hash, session_id)
        assert mock_query.call_count == 2  # Count should increase
        assert resp3 == mock_response

@pytest.mark.asyncio
async def test_metrics_caching(cache_test_session):
    """Test metrics caching."""
    from unittest.mock import AsyncMock

    project_hash, session_id, session_path = cache_test_session
    clear_all_caches()

    mock_metrics = SessionMetricsResponse(
        tokens=TokenUsage(input_tokens=100),
        cost=CostBreakdown(),
        duration_seconds=10,
        message_count=1,
        tool_calls=0,
        error_count=0,
        cache_hit_rate=0.0,
        models_used=["test-model"],
        interruption_rate=0.0
    )

    # Patch the async service function where it is imported in the router (Phase 4.2 refactoring)
    with patch("claude_code_tracer.routers.sessions.get_session_metrics_async", new_callable=AsyncMock, return_value=mock_metrics) as mock_query:
        # First call
        await get_session_metrics_endpoint(project_hash, session_id)
        assert mock_query.call_count == 1

        # Second call (cached)
        await get_session_metrics_endpoint(project_hash, session_id)
        assert mock_query.call_count == 1

        # Touch file
        time.sleep(0.01)
        session_path.touch()

        # Third call (re-query)
        await get_session_metrics_endpoint(project_hash, session_id)
        assert mock_query.call_count == 2

@pytest.mark.asyncio
async def test_filter_options_caching(cache_test_session):
    """Test filter options caching."""
    project_hash, session_id, session_path = cache_test_session
    clear_all_caches()
    
    # For filter options, the router does the query logic inside. 
    # We can check the cache directly or patch the cache functions.
    # The router calls get_cached_filter_options first.
    
    # We'll rely on observing if the database calls happen.
    # The router calls get_session_view_query and then executes SQL.
    
    with patch("claude_code_tracer.routers.sessions.get_connection") as mock_conn:
        # Mock DB response
        mock_db = MagicMock()
        mock_conn.return_value.__enter__.return_value = mock_db
        mock_db.execute.return_value.fetchall.return_value = [] # tools
        mock_db.execute.return_value.fetchone.return_value = [0] # error count
        
        # 1. First call
        await get_session_message_filters(project_hash, session_id)
        # Should execute queries
        assert mock_db.execute.called
        call_count_initial = mock_db.execute.call_count
        
        # 2. Second call
        await get_session_message_filters(project_hash, session_id)
        # Should not execute more queries
        assert mock_db.execute.call_count == call_count_initial
        
        # 3. Touch file
        time.sleep(0.01)
        session_path.touch()
        
        # 4. Third call
        await get_session_message_filters(project_hash, session_id)
        # Should execute queries again
        assert mock_db.execute.call_count > call_count_initial

def test_cache_size_limit():
    """Test LRU behavior of the cache."""
    clear_all_caches()
    
    # We access the internal store for testing
    from claude_code_tracer.services.cache import _tool_usage_store, cache_tool_usage
    
    # Fill cache with 250 items (limit is 200)
    for i in range(250):
        p = Path(f"/tmp/fake-{i}")
        cache_tool_usage(p, ToolUsageResponse(tools=[], total_calls=0))
        
    # Should have evicted ~50 items, size should be around 200
    # The implementation removes 50 items when > 200, so it drops to 151, then grows.
    # 200 -> +1 -> 201 -> remove 50 -> 151.
    # We added 50 more -> 201 -> remove 50 -> 151.
    # Wait, let's trace:
    # 0..200: adds 201 items. 201 > 200 -> remove 50 -> 151.
    # 201..250: adds 49 items. 151 + 49 = 200.
    
    # So we expect roughly 200 items.
    assert len(_tool_usage_store) <= 200
    
    stats = get_cache_stats()
    assert stats["tool_usage_entries"] <= 200

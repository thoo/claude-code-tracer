import json

from claude_code_tracer.services.database import is_valid_uuid


def test_is_valid_uuid():
    assert is_valid_uuid("550e8400-e29b-41d4-a716-446655440000") is True
    assert is_valid_uuid("not-a-uuid") is False
    assert is_valid_uuid("550e8400-e29b-41d4-a716-44665544000") is False  # too short
    assert is_valid_uuid("550e8400-e29b-41d4-a716-4466554400000") is False  # too long
    assert is_valid_uuid("") is False


def test_list_projects(mock_projects_dir):
    from claude_code_tracer.services.database import list_projects

    # Create a project directory
    project_hash = "test-project"
    (mock_projects_dir / project_hash).mkdir()

    # Create a session file so session_count > 0
    (mock_projects_dir / project_hash / "550e8400-e29b-41d4-a716-446655440000.jsonl").touch()

    projects = list_projects()
    assert len(projects) == 1
    assert projects[0]["path_hash"] == project_hash


def test_duckdb_pool_singleton():
    from claude_code_tracer.services.database import DuckDBPool

    conn1 = DuckDBPool.get_connection()
    conn2 = DuckDBPool.get_connection()

    assert conn1 is not None
    assert conn1 is conn2  # Verify they are the same instance


def test_subagent_discovery_and_caching(mock_projects_dir):
    import orjson

    from claude_code_tracer.services.database import _subagent_cache, get_subagent_files_for_session

    project_hash = "test-project-subagents"
    session_id = "550e8400-e29b-41d4-a716-446655440099"
    project_dir = mock_projects_dir / project_hash
    project_dir.mkdir()

    # 1. Setup: Create "Old Structure" agent file (flat in project dir)
    agent_id_1 = "agent1"
    old_agent_file = project_dir / f"agent-{agent_id_1}.jsonl"
    with open(old_agent_file, "wb") as f:
        f.write(orjson.dumps({"sessionId": session_id}))
        f.write(b"\n")

    # 2. Setup: Create "New Structure" agent file (nested in subagents dir)
    agent_id_2 = "agent2"
    session_dir = project_dir / session_id
    subagents_dir = session_dir / "subagents"
    subagents_dir.mkdir(parents=True)
    new_agent_file = subagents_dir / f"agent-{agent_id_2}.jsonl"
    # New structure files don't strictly need sessionId in header for discovery, but usually have it
    with open(new_agent_file, "wb") as f:
        f.write(orjson.dumps({"sessionId": session_id}))
        f.write(b"\n")

    # Clear cache to ensure clean state
    if project_hash in _subagent_cache:
        del _subagent_cache[project_hash]

    # 3. Verify discovery
    files = get_subagent_files_for_session(project_hash, session_id)
    file_names = {f.name for f in files}

    assert len(files) == 2
    assert f"agent-{agent_id_1}.jsonl" in file_names
    assert f"agent-{agent_id_2}.jsonl" in file_names

    # 4. Verify Caching
    # Manually modify the cache to see if the function returns the cached value
    # instead of hitting the filesystem again
    # Cache structure is: {project_hash: (mtime, {session_id: [paths]})}
    fake_path = project_dir / "fake.jsonl"
    mtime, index = _subagent_cache[project_hash]
    index[session_id].append(fake_path)
    _subagent_cache[project_hash] = (mtime, index)

    cached_files = get_subagent_files_for_session(project_hash, session_id)
    assert fake_path in cached_files
    assert len(cached_files) == 3


def test_session_view_handles_missing_columns(mock_projects_dir):
    """Test that session views handle missing optional columns gracefully."""
    from claude_code_tracer.services.database import (
        get_connection,
        get_or_create_session_view,
        invalidate_session_view,
    )

    project_hash = "missing-cols-test"
    session_id = "550e8400-e29b-41d4-a716-446655440001"
    project_dir = mock_projects_dir / project_hash
    project_dir.mkdir()

    session_path = project_dir / f"{session_id}.jsonl"

    # Create a minimal session file WITHOUT optional columns (sessionId, cwd, data, toolUseID, parentToolUseID)
    with open(session_path, "w") as f:
        # Only uuid, type, timestamp, message - no optional columns
        msg = {
            "uuid": "msg-1",
            "type": "assistant",
            "timestamp": "2024-01-01T12:00:00Z",
            "message": {
                "id": "msg-1",
                "content": "Hello",
                "model": "claude-3-sonnet",
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        }
        f.write(json.dumps(msg) + "\n")

    # Clear any existing view
    invalidate_session_view(session_path)

    # Create the view - should succeed even with missing columns
    view_name = get_or_create_session_view(session_path)
    assert view_name.startswith("session_")

    # Query the view for optional columns - should return NULL, not fail
    with get_connection() as conn:
        # This query would fail if sessionId column doesn't exist
        result = conn.execute(f"SELECT uuid, sessionId, cwd, toolUseID FROM {view_name}").fetchall()

        assert len(result) == 1
        row = result[0]
        assert row[0] == "msg-1"  # uuid exists
        assert row[1] is None  # sessionId is NULL (missing from file)
        assert row[2] is None  # cwd is NULL (missing from file)
        assert row[3] is None  # toolUseID is NULL (missing from file)

    # Cleanup
    invalidate_session_view(session_path)

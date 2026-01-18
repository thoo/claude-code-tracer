import pytest
from pathlib import Path
from claude_code_tracer.services import database

@pytest.fixture
def mock_projects_dir(tmp_path, monkeypatch):
    claude_dir = tmp_path / ".claude"
    projects_dir = claude_dir / "projects"
    projects_dir.mkdir(parents=True)
    
    monkeypatch.setattr(database, "CLAUDE_DIR", claude_dir)
    monkeypatch.setattr(database, "PROJECTS_DIR", projects_dir)
    return projects_dir

@pytest.fixture
def sample_session_file(mock_projects_dir):
    project_hash = "test-project"
    session_id = "550e8400-e29b-41d4-a716-446655440000"
    project_dir = mock_projects_dir / project_hash
    project_dir.mkdir()
    
    session_path = project_dir / f"{session_id}.jsonl"
    
    # Create a sample JSONL file
    with open(session_path, "w") as f:
        # User message
        f.write('{"type": "user", "message": {"content": [{"type": "text", "text": "Hello"}], "id": "m1"}, "timestamp": "2024-01-01T12:00:00Z", "uuid": "u1"}\n')
        # Assistant message with usage
        f.write('{"type": "assistant", "message": {"content": [{"type": "text", "text": "Hi"}], "usage": {"input_tokens": 10, "output_tokens": 20, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 2}, "model": "claude-3-5-sonnet-20241022", "id": "m2"}, "timestamp": "2024-01-01T12:00:05Z", "uuid": "u2"}\n')
        # Tool use
        f.write('{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "ls", "input": {"path": "."}, "id": "t1"}], "id": "m3"}, "timestamp": "2024-01-01T12:00:10Z", "uuid": "u3"}\n')
        # Tool result
        f.write('{"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": "file1.txt"}], "id": "m4"}, "timestamp": "2024-01-01T12:00:11Z", "uuid": "u4"}\n')
    
    return project_hash, session_id, session_path

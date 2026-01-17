"""DuckDB database connection management."""

import json
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import duckdb

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"


@contextmanager
def get_connection() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Get DuckDB connection with proper settings."""
    conn = duckdb.connect(":memory:")
    conn.execute("SET enable_progress_bar = false")
    try:
        yield conn
    finally:
        conn.close()


def get_project_dir(project_hash: str) -> Path:
    """Get path to a project directory."""
    return PROJECTS_DIR / project_hash


def get_session_path(project_hash: str, session_id: str) -> Path:
    """Get path to a session JSONL file."""
    return PROJECTS_DIR / project_hash / f"{session_id}.jsonl"


def get_subagent_path(project_hash: str, agent_id: str) -> Path:
    """Get path to a subagent JSONL file."""
    return PROJECTS_DIR / project_hash / "subagents" / f"{agent_id}.jsonl"


def get_sessions_index_path(project_hash: str) -> Path:
    """Get path to sessions index file."""
    return PROJECTS_DIR / project_hash / "sessions-index.json"


def list_projects() -> list[dict[str, str]]:
    """List all projects from ~/.claude/projects/."""
    if not PROJECTS_DIR.exists():
        return []

    projects = []
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir() or project_dir.name == "-home-":
            continue

        project_path = _get_project_path_from_index(project_dir)
        session_count = len(list(project_dir.glob("*.jsonl")))

        projects.append(
            {
                "path_hash": project_dir.name,
                "project_path": project_path,
                "session_count": session_count,
            }
        )

    return projects


def _get_project_path_from_index(project_dir: Path) -> str:
    """Extract project path from sessions-index.json."""
    index_path = project_dir / "sessions-index.json"
    if not index_path.exists():
        return "Unknown"

    try:
        with open(index_path) as f:
            index_data = json.load(f)
            if isinstance(index_data, list) and index_data:
                return index_data[0].get("directory", "Unknown")
    except (json.JSONDecodeError, KeyError):
        pass

    return "Unknown"


def list_sessions(project_hash: str) -> list[dict[str, str]]:
    """List all sessions for a project."""
    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return []

    sessions = _get_sessions_from_index(project_hash)
    if sessions:
        return sessions

    return [
        {"session_id": f.stem, "slug": None, "directory": str(project_dir)}
        for f in project_dir.glob("*.jsonl")
    ]


def _get_sessions_from_index(project_hash: str) -> list[dict[str, str]]:
    """Get sessions from sessions-index.json if available."""
    index_path = get_sessions_index_path(project_hash)
    if not index_path.exists():
        return []

    try:
        with open(index_path) as f:
            index_data = json.load(f)
            if isinstance(index_data, list):
                return [
                    {
                        "session_id": info.get("id", ""),
                        "slug": info.get("slug", ""),
                        "directory": info.get("directory", ""),
                    }
                    for info in index_data
                ]
    except (json.JSONDecodeError, KeyError):
        pass

    return []

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
    # Agent files are in the same directory as session files, named agent-{id}.jsonl
    return PROJECTS_DIR / project_hash / f"agent-{agent_id}.jsonl"


def get_subagent_files_for_session(project_hash: str, session_id: str) -> list[Path]:
    """Find all subagent files that belong to a session.

    Subagent files have a sessionId field in their first line that matches
    the parent session's UUID.
    """
    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return []

    subagent_files = []
    for agent_file in project_dir.glob("agent-*.jsonl"):
        try:
            with open(agent_file) as f:
                first_line = f.readline()
                if first_line:
                    data = json.loads(first_line)
                    if data.get("sessionId") == session_id:
                        subagent_files.append(agent_file)
        except (json.JSONDecodeError, OSError):
            continue

    return subagent_files


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
    """Extract project path from sessions-index.json or JSONL files."""
    index_path = project_dir / "sessions-index.json"

    # Try sessions-index.json first
    if index_path.exists():
        try:
            with open(index_path) as f:
                index_data = json.load(f)
                # Handle new format: { version: 1, entries: [...] }
                if isinstance(index_data, dict) and "entries" in index_data:
                    entries = index_data.get("entries", [])
                    if entries and isinstance(entries, list):
                        return entries[0].get("projectPath", "Unknown")
                # Handle legacy format: [...]
                elif isinstance(index_data, list) and index_data:
                    return index_data[0].get("projectPath", index_data[0].get("directory", "Unknown"))
        except (json.JSONDecodeError, KeyError):
            pass

    # Fallback: read cwd from JSONL files (exclude agent-* files)
    jsonl_files = [f for f in project_dir.glob("*.jsonl") if not f.name.startswith("agent-")]
    for jsonl_file in jsonl_files[:5]:  # Try first 5 files
        try:
            with open(jsonl_file) as f:
                for i, line in enumerate(f):
                    if i > 20:  # Only check first 20 lines
                        break
                    try:
                        data = json.loads(line)
                        if "cwd" in data and data["cwd"]:
                            return data["cwd"]
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue

    return "Unknown"


def list_sessions(project_hash: str) -> list[dict[str, str]]:
    """List all sessions for a project."""
    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return []

    sessions = _get_sessions_from_index(project_hash)
    if sessions:
        return sessions

    # Fallback: list JSONL files (exclude agent-* subagent files)
    return [
        {"session_id": f.stem, "slug": None, "directory": str(project_dir)}
        for f in project_dir.glob("*.jsonl")
        if not f.name.startswith("agent-")
    ]


def _get_sessions_from_index(project_hash: str) -> list[dict[str, str]]:
    """Get sessions from sessions-index.json if available."""
    index_path = get_sessions_index_path(project_hash)
    if not index_path.exists():
        return []

    try:
        with open(index_path) as f:
            index_data = json.load(f)

            # Handle new format: { version: 1, entries: [...] }
            entries = []
            if isinstance(index_data, dict) and "entries" in index_data:
                entries = index_data.get("entries", [])
            # Handle legacy format: [...]
            elif isinstance(index_data, list):
                entries = index_data

            return [
                {
                    "session_id": info.get("sessionId", info.get("id", "")),
                    "slug": info.get("slug", ""),
                    "directory": info.get("projectPath", info.get("directory", "")),
                }
                for info in entries
            ]
    except (json.JSONDecodeError, KeyError):
        pass

    return []

"""DuckDB database connection management."""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from re import compile as re_compile

import duckdb
import orjson

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
UUID_PATTERN = re_compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def is_valid_uuid(val: str) -> bool:
    """Check if a string is a valid UUID."""
    return bool(UUID_PATTERN.match(val))


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
    """Get path to a subagent JSONL file (agent-{id}.jsonl).

    Searches in multiple locations:
    1. {project_dir}/{session_id}/subagents/agent-{id}.jsonl (new structure)
    2. {project_dir}/agent-{id}.jsonl (old structure)
    """
    project_dir = get_project_dir(project_hash)
    agent_filename = f"agent-{agent_id}.jsonl"

    # Search in session subdirectories (new structure)
    for session_dir in project_dir.iterdir():
        if session_dir.is_dir():
            subagents_dir = session_dir / "subagents"
            if subagents_dir.exists():
                agent_path = subagents_dir / agent_filename
                if agent_path.exists():
                    return agent_path

    # Fall back to old structure (direct in project dir)
    return project_dir / agent_filename


def get_subagent_path_for_session(
    project_hash: str, session_id: str, agent_id: str
) -> Path | None:
    """Get path to a specific subagent JSONL file for a session.

    Searches in:
    1. {project_dir}/{session_id}/subagents/agent-{agent_id}.jsonl (new structure)
    2. {project_dir}/agent-{agent_id}.jsonl (old structure, with sessionId match)

    Returns None if the agent file doesn't exist.
    """
    project_dir = get_project_dir(project_hash)
    agent_filename = f"agent-{agent_id}.jsonl"

    # Check new structure first: {session_id}/subagents/
    new_path = project_dir / session_id / "subagents" / agent_filename
    if new_path.exists():
        return new_path

    # Check old structure: direct in project dir
    old_path = project_dir / agent_filename
    if old_path.exists():
        # Verify it belongs to this session by checking sessionId in first line
        try:
            with open(old_path, "rb") as f:
                first_line = f.readline()
                if first_line:
                    data = orjson.loads(first_line)
                    if data.get("sessionId") == session_id:
                        return old_path
        except (orjson.JSONDecodeError, OSError):
            pass

    return None


def get_subagent_files_for_session(project_hash: str, session_id: str) -> list[Path]:
    """Find all subagent files that belong to a session.

    Checks both:
    1. {project_dir}/{session_id}/subagents/ directory (new structure)
    2. Files in project_dir with matching sessionId (old structure)
    """
    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return []

    subagent_files = []

    # Check new structure: {session_id}/subagents/
    session_subagents_dir = project_dir / session_id / "subagents"
    if session_subagents_dir.exists():
        for agent_file in session_subagents_dir.glob("agent-*.jsonl"):
            subagent_files.append(agent_file)

    # Also check old structure: files directly in project_dir
    for agent_file in project_dir.glob("agent-*.jsonl"):
        try:
            with open(agent_file, "rb") as f:
                first_line = f.readline()
                if first_line:
                    data = orjson.loads(first_line)
                    if data.get("sessionId") == session_id:
                        subagent_files.append(agent_file)
        except (orjson.JSONDecodeError, OSError):
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
        session_count = len(list_sessions(project_dir.name))

        projects.append({
            "path_hash": project_dir.name,
            "project_path": project_path,
            "session_count": session_count,
        })

    return projects


def _get_project_path_from_index(project_dir: Path) -> str:
    """Extract project path from sessions-index.json or JSONL files."""
    index_path = project_dir / "sessions-index.json"

    if index_path.exists():
        project_path = _extract_project_path_from_index(index_path)
        if project_path:
            return project_path

    return _extract_project_path_from_jsonl(project_dir)


def _extract_project_path_from_index(index_path: Path) -> str | None:
    """Extract project path from sessions-index.json file."""
    try:
        with open(index_path, "rb") as f:
            index_data = orjson.loads(f.read())
    except (orjson.JSONDecodeError, OSError):
        return None

    entries = _extract_index_entries(index_data)
    if not entries:
        return None

    first_entry = entries[0]
    return first_entry.get("projectPath") or first_entry.get("directory")


def _extract_project_path_from_jsonl(project_dir: Path) -> str:
    """Extract project path from JSONL files by reading cwd field."""
    jsonl_files = [
        f for f in project_dir.glob("*.jsonl")
        if not f.name.startswith("agent-")
    ]

    for jsonl_file in jsonl_files[:5]:
        try:
            with open(jsonl_file, "rb") as f:
                for i, line in enumerate(f):
                    if i > 20:
                        break
                    try:
                        data = orjson.loads(line)
                        if cwd := data.get("cwd"):
                            return cwd
                    except orjson.JSONDecodeError:
                        continue
        except OSError:
            continue

    return "Unknown"


def _extract_index_entries(index_data: dict | list) -> list[dict]:
    """Extract entries from index data, handling both new and legacy formats."""
    if isinstance(index_data, dict) and "entries" in index_data:
        return index_data.get("entries", [])
    if isinstance(index_data, list):
        return index_data
    return []


def list_sessions(project_hash: str) -> list[dict[str, str]]:
    """List all sessions for a project.

    Merges sessions from both the index file and filesystem scan to ensure
    all sessions are discovered, even if the index is out of date.
    """
    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return []

    # Get sessions from index (deduplicate by session_id)
    seen_ids: set[str] = set()
    sessions: list[dict[str, str]] = []

    for session in _get_sessions_from_index(project_hash):
        session_id = session["session_id"]
        if session_id and session_id not in seen_ids:
            seen_ids.add(session_id)
            sessions.append(session)

    # Scan filesystem for any sessions not in index
    for f in project_dir.glob("*.jsonl"):
        if f.name.startswith("agent-"):
            continue
        if not is_valid_uuid(f.stem):
            continue
        if f.stem in seen_ids:
            continue
        seen_ids.add(f.stem)
        sessions.append({
            "session_id": f.stem,
            "slug": None,
            "directory": str(project_dir),
        })

    return sessions


def _get_sessions_from_index(project_hash: str) -> list[dict[str, str]]:
    """Get sessions from sessions-index.json if available."""
    index_path = get_sessions_index_path(project_hash)
    if not index_path.exists():
        return []

    try:
        with open(index_path, "rb") as f:
            index_data = orjson.loads(f.read())
    except (orjson.JSONDecodeError, OSError):
        return []

    entries = _extract_index_entries(index_data)
    return [
        {
            "session_id": entry.get("sessionId") or entry.get("id", ""),
            "slug": entry.get("slug", ""),
            "directory": entry.get("projectPath") or entry.get("directory", ""),
        }
        for entry in entries
    ]

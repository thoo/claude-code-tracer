"""DuckDB database connection management."""

import threading
import time
from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from re import compile as re_compile

import duckdb
import orjson
from loguru import logger

from claude_code_tracer.services.queries import _JSON_OPTS

CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
UUID_PATTERN = re_compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

# Session view cache: {session_path: (view_name, created_time, file_mtime)}
_session_views: dict[str, tuple[str, float, float]] = {}
_session_views_lock = threading.Lock()
SESSION_VIEW_TTL = 300  # 5 minutes

# Optional columns that may be missing from some session files.
# When creating views, we add NULL for any missing columns to prevent query failures.
OPTIONAL_COLUMNS = {"sessionId", "cwd", "data", "toolUseID", "parentToolUseID"}


def is_valid_uuid(val: str) -> bool:
    """Check if a string is a valid UUID."""
    return bool(UUID_PATTERN.match(val))


class DuckDBPool:
    """Thread-safe singleton for DuckDB connection."""

    _instance: duckdb.DuckDBPyConnection | None = None
    _lock = threading.RLock()

    @classmethod
    def get_connection(cls) -> duckdb.DuckDBPyConnection:
        """Get or create the shared DuckDB connection."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = duckdb.connect(":memory:")
                cls._instance.execute("SET enable_progress_bar = false")
            return cls._instance

    @classmethod
    def close(cls) -> None:
        """Close the connection if it exists."""
        with cls._lock:
            if cls._instance is not None:
                cls._instance.close()
                cls._instance = None

            # Clear session views cache as views are lost when connection closes
            with _session_views_lock:
                _session_views.clear()


@contextmanager
def get_connection() -> Generator[duckdb.DuckDBPyConnection, None, None]:
    """Get a cursor for the persistent DuckDB connection.

    Yields a cursor (which allows concurrent execution from multiple threads)
    instead of the raw connection. This prevents heap corruption issues
    when multiple threads try to execute queries on the same connection object.
    """
    conn = DuckDBPool.get_connection()
    # Create a new cursor for this thread/request
    cursor = conn.cursor()
    try:
        yield cursor
    finally:
        cursor.close()


def get_or_create_session_view(session_path: Path) -> str:
    """Get or create a temporary view for a session file.

    This optimization (Priority 2.3) creates a temporary DuckDB view for the
    session file, avoiding repeated read_json_auto() calls when multiple
    queries need the same session data (e.g., /messages, /metrics, /tools).

    The view is cached based on file path and mtime, and automatically
    invalidated when the file changes or after TTL expires.

    Returns:
        The view name to use in queries
    """
    path_str = str(session_path)

    if not session_path.exists():
        raise FileNotFoundError(f"Session file not found: {path_str}")

    current_mtime = session_path.stat().st_mtime
    current_time = time.time()

    with _session_views_lock:
        if path_str in _session_views:
            view_name, created_time, cached_mtime = _session_views[path_str]

            # Check if view is still valid (not expired and file unchanged)
            if current_time - created_time < SESSION_VIEW_TTL and cached_mtime == current_mtime:
                # Verify view actually exists in DB (safeguard against connection resets)
                try:
                    # Quick check using a cursor
                    conn = DuckDBPool.get_connection()
                    conn.execute(f"SELECT 1 FROM {view_name} LIMIT 0")
                    return view_name
                except Exception:
                    # View missing, remove from cache and recreate
                    pass

            # View is stale or missing, remove from cache
            try:
                conn = DuckDBPool.get_connection()
                conn.execute(f"DROP VIEW IF EXISTS {view_name}")
            except Exception:
                pass
            if path_str in _session_views:
                del _session_views[path_str]

        # Create new view
        view_name = f"session_{abs(hash(path_str)) % 100000}"

        conn = DuckDBPool.get_connection()
        try:
            # First, detect which columns exist in the file
            source = f"read_json_auto('{path_str}', {_JSON_OPTS})"
            result = conn.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
            existing_columns = {row[0] for row in result}

            # Build SELECT list: include all existing columns, add NULL for missing optional columns
            missing_optionals = OPTIONAL_COLUMNS - existing_columns
            if missing_optionals:
                # Need to explicitly select columns and add NULLs for missing ones
                select_parts = ["*"]
                for col in missing_optionals:
                    select_parts.append(f"NULL AS {col}")
                select_clause = ", ".join(select_parts)
            else:
                select_clause = "*"

            # Use regular view (not TEMPORARY) because temporary views are not
            # visible to cursors created from the same connection in DuckDB
            conn.execute(f"""
                CREATE OR REPLACE VIEW {view_name} AS
                SELECT {select_clause}
                FROM read_json_auto(
                    '{path_str}',
                    {_JSON_OPTS}
                )
            """)
            _session_views[path_str] = (view_name, current_time, current_mtime)
            return view_name
        except Exception as e:
            logger.debug(f"Failed to create session view: {e}")
            # Return path string for direct read_json_auto() usage
            raise


def invalidate_session_view(session_path: Path) -> None:
    """Invalidate a session view (call when session is modified)."""
    path_str = str(session_path)

    with _session_views_lock:
        if path_str in _session_views:
            view_name, _, _ = _session_views[path_str]
            try:
                conn = DuckDBPool.get_connection()
                conn.execute(f"DROP VIEW IF EXISTS {view_name}")
            except Exception:
                pass
            del _session_views[path_str]


def cleanup_stale_views() -> int:
    """Clean up expired session views. Returns count of views cleaned."""
    current_time = time.time()
    cleaned = 0

    with _session_views_lock:
        stale_paths = [
            path_str
            for path_str, (_, created_time, _) in _session_views.items()
            if current_time - created_time >= SESSION_VIEW_TTL
        ]

        conn = DuckDBPool.get_connection()
        for path_str in stale_paths:
            view_name, _, _ = _session_views[path_str]
            try:
                conn.execute(f"DROP VIEW IF EXISTS {view_name}")
            except Exception:
                pass
            del _session_views[path_str]
            cleaned += 1

    return cleaned


def _get_missing_columns(session_path: Path) -> set[str]:
    """Detect which optional columns are missing from a session file."""
    source = f"read_json_auto('{session_path}', {_JSON_OPTS})"
    try:
        conn = DuckDBPool.get_connection()
        result = conn.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
        existing_columns = {row[0] for row in result}
        return OPTIONAL_COLUMNS - existing_columns
    except Exception:
        return set()  # Assume no missing columns on error


def _build_safe_source(session_path: Path) -> str:
    """Build a read_json_auto expression that adds NULL for missing optional columns.

    This ensures queries don't fail when accessing columns that don't exist in the file.
    """
    source = f"read_json_auto('{session_path}', {_JSON_OPTS})"
    missing = _get_missing_columns(session_path)
    if not missing:
        return source

    # Wrap in a subquery that adds NULL for missing columns
    null_cols = ", ".join(f"NULL AS {col}" for col in missing)
    return f"(SELECT *, {null_cols} FROM {source})"


def get_session_view_query(session_path: Path) -> str:
    """Get a query source for session data - either view name or read_json_auto.

    This is a fallback-safe version that tries to use a view but falls back
    to direct file reading if view creation fails. Both paths handle missing
    optional columns by adding NULL placeholders.
    """
    try:
        view_name = get_or_create_session_view(session_path)
        return view_name
    except Exception:
        # Fall back to direct read with missing column handling
        return _build_safe_source(session_path)


# Required columns for message queries
REQUIRED_MESSAGE_COLUMNS = {"uuid", "timestamp", "message", "type"}


def session_has_messages(session_path: Path) -> bool:
    """Check if a session file has the required columns for message queries.

    Some session files only contain metadata (summary, file-history-snapshot)
    without actual message data. This function validates the schema before
    attempting to run message queries.

    Returns:
        True if the session has message data, False otherwise.
    """
    if not session_path.exists():
        return False

    source = f"read_json_auto('{session_path}', {_JSON_OPTS})"

    try:
        conn = DuckDBPool.get_connection()
        cursor = conn.cursor()
        try:
            # Get column names from the file
            result = cursor.execute(f"DESCRIBE SELECT * FROM {source}").fetchall()
            columns = {row[0] for row in result}

            # Check if required columns exist
            return REQUIRED_MESSAGE_COLUMNS.issubset(columns)
        finally:
            cursor.close()
    except Exception as e:
        logger.debug(f"Failed to check session schema: {e}")
        return False


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


def get_subagent_path_for_session(project_hash: str, session_id: str, agent_id: str) -> Path | None:
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


# Cache: {project_hash: (mtime, {session_id: [paths]})}
_subagent_cache: dict[str, tuple[float, dict[str, list[Path]]]] = {}


def _build_subagent_index(project_dir: Path) -> dict[str, list[Path]]:
    """Build mapping of session_id -> subagent file paths."""
    index: dict[str, list[Path]] = defaultdict(list)

    for agent_file in project_dir.glob("**/agent-*.jsonl"):
        session_id = _extract_session_id_from_agent_file(agent_file)
        if session_id:
            index[session_id].append(agent_file)

    return index


def _extract_session_id_from_agent_file(agent_file: Path) -> str | None:
    """Extract session ID from agent file path or content."""
    # Fast path: check directory structure {session_id}/subagents/agent-*.jsonl
    if agent_file.parent.name == "subagents":
        session_id = agent_file.parent.parent.name
        if is_valid_uuid(session_id):
            return session_id

    # Slow path: read sessionId from file header
    try:
        with open(agent_file, "rb") as f:
            first_line = f.readline()
            if first_line:
                data = orjson.loads(first_line)
                return data.get("sessionId")
    except (orjson.JSONDecodeError, OSError) as e:
        logger.debug(f"Could not parse subagent file {agent_file}: {e}")

    return None


def get_subagent_files_for_session(project_hash: str, session_id: str) -> list[Path]:
    """Find all subagent files for a session.

    Uses a cached index with mtime-based invalidation.
    """
    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return []

    current_mtime = project_dir.stat().st_mtime
    cached = _subagent_cache.get(project_hash)

    if cached is None or cached[0] < current_mtime:
        index = _build_subagent_index(project_dir)
        _subagent_cache[project_hash] = (current_mtime, index)
        cached = _subagent_cache[project_hash]

    return cached[1].get(session_id, [])


def get_sessions_index_path(project_hash: str) -> Path:
    """Get path to sessions index file."""
    return PROJECTS_DIR / project_hash / "sessions-index.json"


def list_projects() -> list[dict[str, str | int]]:
    """List all projects from ~/.claude/projects/."""
    if not PROJECTS_DIR.exists():
        return []

    projects: list[dict[str, str | int]] = []
    for project_dir in PROJECTS_DIR.iterdir():
        if not project_dir.is_dir() or project_dir.name == "-home-":
            continue

        project_path = _get_project_path_from_index(project_dir)
        session_count = len(list_sessions(project_dir.name))

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
    jsonl_files = [f for f in project_dir.glob("*.jsonl") if not f.name.startswith("agent-")]

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


def list_sessions(project_hash: str) -> list[dict[str, str | None]]:
    """List all sessions for a project.

    Merges sessions from both the index file and filesystem scan to ensure
    all sessions are discovered, even if the index is out of date.
    """
    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return []

    # Get sessions from index (deduplicate by session_id)
    seen_ids: set[str] = set()
    sessions: list[dict[str, str | None]] = []

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
        sessions.append(
            {
                "session_id": f.stem,
                "slug": None,
                "directory": str(project_dir),
            }
        )

    return sessions


def _get_sessions_from_index(project_hash: str) -> list[dict[str, str | None]]:
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

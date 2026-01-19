"""Query result caching service for static session data.

This module provides file-mtime-based caching for expensive queries that
return data which only changes when the underlying session file changes.

Priority 3.6 optimization: Cache tool usage, metrics, filter options, and
subagent data to avoid re-querying on repeated navigation.

Priority 4.3 optimization: Persistent cache for incremental aggregates to
avoid re-calculating metrics for completed sessions.
"""

import threading
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, TypeVar

import orjson
from loguru import logger

from ..models.responses import (
    MessageFilterOptions,
    SessionMetricsResponse,
    SubagentListResponse,
    ToolUsageResponse,
)

T = TypeVar("T")

# Persistent cache location
CLAUDE_DIR = Path.home() / ".claude"
CACHE_FILE = CLAUDE_DIR / "tracer-cache.json"


# ============================================================================
# Persistent Cache for Incremental Aggregates (Priority 4.3)
# ============================================================================


@dataclass
class SessionAggregateMetrics:
    """Cached aggregate metrics for a single session."""

    session_id: str
    status: str  # "completed", "running", etc.
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    total_cost: float = 0.0
    message_count: int = 0
    tool_calls: int = 0
    error_count: int = 0
    first_activity: str | None = None  # ISO timestamp
    last_activity: str | None = None  # ISO timestamp
    mtime: float = 0.0  # File modification time for invalidation


@dataclass
class ProjectAggregateCache:
    """Cached aggregates for a project's sessions."""

    project_hash: str
    sessions: dict[str, SessionAggregateMetrics] = field(default_factory=dict)
    last_updated: float = 0.0


class PersistentCache:
    """Persistent cache for session aggregates.

    This cache stores aggregated metrics for completed sessions to avoid
    re-parsing JSONL files on every request. Data is persisted to disk
    at ~/.claude/tracer-cache.json.

    Cache invalidation:
    - Sessions with status "completed" are cached indefinitely
    - Sessions with other statuses are re-validated on every request
    - File mtime changes invalidate individual session entries
    """

    _instance: "PersistentCache | None" = None
    _lock = threading.RLock()
    _projects: dict[str, ProjectAggregateCache]
    _dirty: bool

    def __new__(cls) -> "PersistentCache":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._projects = {}
                cls._instance._dirty = False
                cls._instance._load()
            return cls._instance

    def _load(self) -> None:
        """Load cache from disk."""
        if not CACHE_FILE.exists():
            return

        try:
            with open(CACHE_FILE, "rb") as f:
                data = orjson.loads(f.read())

            for project_hash, project_data in data.get("projects", {}).items():
                sessions = {}
                for session_id, session_data in project_data.get("sessions", {}).items():
                    sessions[session_id] = SessionAggregateMetrics(
                        session_id=session_id,
                        status=session_data.get("status", "unknown"),
                        input_tokens=session_data.get("input_tokens", 0),
                        output_tokens=session_data.get("output_tokens", 0),
                        cache_creation_input_tokens=session_data.get(
                            "cache_creation_input_tokens", 0
                        ),
                        cache_read_input_tokens=session_data.get("cache_read_input_tokens", 0),
                        total_cost=session_data.get("total_cost", 0.0),
                        message_count=session_data.get("message_count", 0),
                        tool_calls=session_data.get("tool_calls", 0),
                        error_count=session_data.get("error_count", 0),
                        first_activity=session_data.get("first_activity"),
                        last_activity=session_data.get("last_activity"),
                        mtime=session_data.get("mtime", 0.0),
                    )

                self._projects[project_hash] = ProjectAggregateCache(
                    project_hash=project_hash,
                    sessions=sessions,
                    last_updated=project_data.get("last_updated", 0.0),
                )

            logger.debug(f"Loaded persistent cache: {len(self._projects)} projects")

        except (orjson.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load persistent cache: {e}")

    def save(self) -> None:
        """Save cache to disk if dirty."""
        with self._lock:
            if not self._dirty:
                return

            try:
                CLAUDE_DIR.mkdir(parents=True, exist_ok=True)

                data = {
                    "version": 1,
                    "projects": {
                        ph: {
                            "project_hash": pc.project_hash,
                            "sessions": {sid: asdict(sm) for sid, sm in pc.sessions.items()},
                            "last_updated": pc.last_updated,
                        }
                        for ph, pc in self._projects.items()
                    },
                }

                with open(CACHE_FILE, "wb") as f:
                    f.write(orjson.dumps(data, option=orjson.OPT_INDENT_2))

                self._dirty = False
                logger.debug(f"Saved persistent cache: {len(self._projects)} projects")

            except OSError as e:
                logger.warning(f"Failed to save persistent cache: {e}")

    def get_session_metrics(
        self, project_hash: str, session_id: str, file_mtime: float
    ) -> SessionAggregateMetrics | None:
        """Get cached metrics for a session if valid.

        Returns None if:
        - Session not in cache
        - Session status is not "completed" (needs re-validation)
        - File mtime has changed (cache invalidated)
        """
        with self._lock:
            project = self._projects.get(project_hash)
            if not project:
                return None

            session = project.sessions.get(session_id)
            if not session:
                return None

            # Only trust cache for completed sessions
            if session.status != "completed":
                return None

            # Check mtime for invalidation
            if session.mtime != file_mtime:
                return None

            return session

    def set_session_metrics(self, project_hash: str, metrics: SessionAggregateMetrics) -> None:
        """Store metrics for a session."""
        with self._lock:
            if project_hash not in self._projects:
                self._projects[project_hash] = ProjectAggregateCache(project_hash=project_hash)

            self._projects[project_hash].sessions[metrics.session_id] = metrics
            self._projects[project_hash].last_updated = metrics.mtime
            self._dirty = True

    def get_project_cached_totals(self, project_hash: str) -> tuple[dict[str, Any], set[str]]:
        """Get cached totals for completed sessions in a project.

        Returns:
            (totals_dict, cached_session_ids) - totals for cached sessions and their IDs
        """
        with self._lock:
            project = self._projects.get(project_hash)
            if not project:
                return {}, set()

            totals: dict[str, Any] = {
                "input_tokens": 0,
                "output_tokens": 0,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
                "total_cost": 0.0,
                "message_count": 0,
                "tool_calls": 0,
                "error_count": 0,
            }
            cached_ids: set[str] = set()

            for session_id, session in project.sessions.items():
                # Only use cache for completed sessions
                if session.status != "completed":
                    continue

                totals["input_tokens"] += session.input_tokens
                totals["output_tokens"] += session.output_tokens
                totals["cache_creation_input_tokens"] += session.cache_creation_input_tokens
                totals["cache_read_input_tokens"] += session.cache_read_input_tokens
                totals["total_cost"] += session.total_cost
                totals["message_count"] += session.message_count
                totals["tool_calls"] += session.tool_calls
                totals["error_count"] += session.error_count
                cached_ids.add(session_id)

            return totals, cached_ids

    def invalidate_session(self, project_hash: str, session_id: str) -> None:
        """Invalidate a specific session's cache entry."""
        with self._lock:
            project = self._projects.get(project_hash)
            if project and session_id in project.sessions:
                del project.sessions[session_id]
                self._dirty = True

    def invalidate_project(self, project_hash: str) -> None:
        """Invalidate all cached data for a project."""
        with self._lock:
            if project_hash in self._projects:
                del self._projects[project_hash]
                self._dirty = True

    def clear(self) -> None:
        """Clear all cached data."""
        with self._lock:
            self._projects.clear()
            self._dirty = True


# Singleton accessor
_persistent_cache: PersistentCache | None = None


def get_persistent_cache() -> PersistentCache:
    """Get the persistent cache singleton."""
    global _persistent_cache
    if _persistent_cache is None:
        _persistent_cache = PersistentCache()
    return _persistent_cache


# ============================================================================
# In-Memory Query Result Caches (Priority 3.6)
# ============================================================================


def _get_file_mtime(path: Path) -> float:
    """Get file modification time, returning 0 if file doesn't exist."""
    try:
        return path.stat().st_mtime
    except (OSError, FileNotFoundError):
        return 0.0


# Cache for tool usage queries - keyed by (path, mtime)
@lru_cache(maxsize=200)
def _cached_tool_usage(path_str: str, mtime: float) -> ToolUsageResponse | None:
    """Internal cached implementation - returns None to indicate cache miss."""
    # This is a placeholder - the actual query happens in the caller
    # The cache stores results after they're computed
    return None


# Cache for session metrics - keyed by (path, mtime)
@lru_cache(maxsize=200)
def _cached_session_metrics(path_str: str, mtime: float) -> SessionMetricsResponse | None:
    """Internal cached implementation - returns None to indicate cache miss."""
    return None


# Cache for message filter options - keyed by (path, mtime)
@lru_cache(maxsize=200)
def _cached_filter_options(path_str: str, mtime: float) -> MessageFilterOptions | None:
    """Internal cached implementation - returns None to indicate cache miss."""
    return None


# Cache for subagent list - keyed by (path, mtime)
@lru_cache(maxsize=200)
def _cached_subagent_list(path_str: str, mtime: float) -> SubagentListResponse | None:
    """Internal cached implementation - returns None to indicate cache miss."""
    return None


# Store computed results
_tool_usage_store: dict[tuple[str, float], ToolUsageResponse] = {}
_metrics_store: dict[tuple[str, float], SessionMetricsResponse] = {}
_filters_store: dict[tuple[str, float], MessageFilterOptions] = {}
_subagents_store: dict[tuple[str, float], SubagentListResponse] = {}


def get_cached_tool_usage(session_path: Path) -> ToolUsageResponse | None:
    """Get cached tool usage for a session, or None if not cached.

    The cache is automatically invalidated when the file mtime changes.
    """
    mtime = _get_file_mtime(session_path)
    key = (str(session_path), mtime)
    return _tool_usage_store.get(key)


def cache_tool_usage(session_path: Path, result: ToolUsageResponse) -> None:
    """Store tool usage result in cache."""
    mtime = _get_file_mtime(session_path)
    key = (str(session_path), mtime)
    _tool_usage_store[key] = result

    # Limit cache size
    if len(_tool_usage_store) > 200:
        # Remove oldest entries (first 50)
        keys_to_remove = list(_tool_usage_store.keys())[:50]
        for k in keys_to_remove:
            del _tool_usage_store[k]


def get_cached_metrics(session_path: Path) -> SessionMetricsResponse | None:
    """Get cached session metrics, or None if not cached."""
    mtime = _get_file_mtime(session_path)
    key = (str(session_path), mtime)
    return _metrics_store.get(key)


def cache_metrics(session_path: Path, result: SessionMetricsResponse) -> None:
    """Store session metrics result in cache."""
    mtime = _get_file_mtime(session_path)
    key = (str(session_path), mtime)
    _metrics_store[key] = result

    if len(_metrics_store) > 200:
        keys_to_remove = list(_metrics_store.keys())[:50]
        for k in keys_to_remove:
            del _metrics_store[k]


def get_cached_filter_options(session_path: Path) -> MessageFilterOptions | None:
    """Get cached filter options, or None if not cached."""
    mtime = _get_file_mtime(session_path)
    key = (str(session_path), mtime)
    return _filters_store.get(key)


def cache_filter_options(session_path: Path, result: MessageFilterOptions) -> None:
    """Store filter options result in cache."""
    mtime = _get_file_mtime(session_path)
    key = (str(session_path), mtime)
    _filters_store[key] = result

    if len(_filters_store) > 200:
        keys_to_remove = list(_filters_store.keys())[:50]
        for k in keys_to_remove:
            del _filters_store[k]


def get_cached_subagents(session_path: Path) -> SubagentListResponse | None:
    """Get cached subagent list, or None if not cached."""
    mtime = _get_file_mtime(session_path)
    key = (str(session_path), mtime)
    return _subagents_store.get(key)


def cache_subagents(session_path: Path, result: SubagentListResponse) -> None:
    """Store subagent list result in cache."""
    mtime = _get_file_mtime(session_path)
    key = (str(session_path), mtime)
    _subagents_store[key] = result

    if len(_subagents_store) > 200:
        keys_to_remove = list(_subagents_store.keys())[:50]
        for k in keys_to_remove:
            del _subagents_store[k]


def clear_all_caches() -> None:
    """Clear all query result caches.

    Call this on application shutdown or when you need to force cache refresh.
    """
    _tool_usage_store.clear()
    _metrics_store.clear()
    _filters_store.clear()
    _subagents_store.clear()

    # Clear lru_cache instances
    _cached_tool_usage.cache_clear()
    _cached_session_metrics.cache_clear()
    _cached_filter_options.cache_clear()
    _cached_subagent_list.cache_clear()


def get_cache_stats() -> dict:
    """Get statistics about cache usage."""
    return {
        "tool_usage_entries": len(_tool_usage_store),
        "metrics_entries": len(_metrics_store),
        "filter_options_entries": len(_filters_store),
        "subagents_entries": len(_subagents_store),
    }

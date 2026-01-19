"""Async wrappers for blocking file I/O operations.

This module provides async versions of blocking file operations to prevent
the FastAPI event loop from being blocked during heavy I/O.

Priority 4.2 implementation: Uses asyncio.to_thread to offload blocking
operations to a thread pool.
"""

import asyncio
from pathlib import Path
from typing import Any

from ..models.responses import (
    CodeChangesResponse,
    ErrorsResponse,
    SessionMetricsResponse,
    SessionSummary,
    SkillsResponse,
    SubagentListResponse,
    ToolUsageResponse,
)
from .cache import get_persistent_cache
from .database import (
    get_session_path,
)
from .database import (
    list_projects as sync_list_projects,
)
from .database import (
    list_sessions as sync_list_sessions,
)
from .index import (
    get_global_index,
    get_projects_from_index,
    get_sessions_from_index,
)
from .log_parser import (
    get_all_projects_metrics as sync_get_all_projects_metrics,
)
from .log_parser import (
    get_project_total_metrics as sync_get_project_total_metrics,
)
from .log_parser import (
    get_session_code_changes as sync_get_session_code_changes,
)
from .log_parser import (
    get_session_errors as sync_get_session_errors,
)
from .log_parser import (
    get_session_metrics as sync_get_session_metrics,
)
from .log_parser import (
    get_session_skills as sync_get_session_skills,
)
from .log_parser import (
    get_session_subagents as sync_get_session_subagents,
)
from .log_parser import (
    get_session_tool_usage as sync_get_session_tool_usage,
)
from .log_parser import (
    parse_session_summary as sync_parse_session_summary,
)

# ============================================================================
# Async Project/Session Discovery
# ============================================================================


async def list_projects_async() -> list[dict[str, str | int]]:
    """List all projects asynchronously.

    Uses the global index if initialized, otherwise falls back to filesystem scan
    in a thread pool.
    """
    index = get_global_index()
    if index.is_initialized:
        return get_projects_from_index()
    return await asyncio.to_thread(sync_list_projects)


async def list_sessions_async(project_hash: str) -> list[dict[str, str | None]]:
    """List all sessions for a project asynchronously.

    Uses the global index if initialized, otherwise falls back to filesystem scan
    in a thread pool.
    """
    index = get_global_index()
    if index.is_initialized:
        return get_sessions_from_index(project_hash)
    return await asyncio.to_thread(sync_list_sessions, project_hash)


# ============================================================================
# Async Session Parsing
# ============================================================================


async def parse_session_summary_async(project_hash: str, session_id: str) -> SessionSummary | None:
    """Parse session summary asynchronously."""
    return await asyncio.to_thread(sync_parse_session_summary, project_hash, session_id)


async def get_session_tool_usage_async(project_hash: str, session_id: str) -> ToolUsageResponse:
    """Get session tool usage asynchronously."""
    return await asyncio.to_thread(sync_get_session_tool_usage, project_hash, session_id)


async def get_session_metrics_async(project_hash: str, session_id: str) -> SessionMetricsResponse:
    """Get session metrics asynchronously."""
    return await asyncio.to_thread(sync_get_session_metrics, project_hash, session_id)


async def get_session_subagents_async(project_hash: str, session_id: str) -> SubagentListResponse:
    """Get session subagents asynchronously."""
    return await asyncio.to_thread(sync_get_session_subagents, project_hash, session_id)


async def get_session_skills_async(project_hash: str, session_id: str) -> SkillsResponse:
    """Get session skills asynchronously."""
    return await asyncio.to_thread(sync_get_session_skills, project_hash, session_id)


async def get_session_code_changes_async(project_hash: str, session_id: str) -> CodeChangesResponse:
    """Get session code changes asynchronously."""
    return await asyncio.to_thread(sync_get_session_code_changes, project_hash, session_id)


async def get_session_errors_async(project_hash: str, session_id: str) -> ErrorsResponse:
    """Get session errors asynchronously."""
    return await asyncio.to_thread(sync_get_session_errors, project_hash, session_id)


# ============================================================================
# Async Aggregation
# ============================================================================


async def get_project_total_metrics_async(
    project_hash: str, session_ids: list[str] | None = None
) -> dict[str, Any]:
    """Get project total metrics asynchronously."""
    return await asyncio.to_thread(sync_get_project_total_metrics, project_hash, session_ids)


async def get_all_projects_metrics_async() -> dict[str, dict[str, Any]]:
    """Get all projects metrics asynchronously."""
    return await asyncio.to_thread(sync_get_all_projects_metrics)


# ============================================================================
# Async File Utilities
# ============================================================================


async def check_session_exists_async(project_hash: str, session_id: str) -> bool:
    """Check if a session file exists asynchronously."""

    def check() -> bool:
        return get_session_path(project_hash, session_id).exists()

    return await asyncio.to_thread(check)


async def get_file_mtime_async(path: Path) -> float:
    """Get file modification time asynchronously."""

    def get_mtime() -> float:
        try:
            return path.stat().st_mtime
        except (OSError, FileNotFoundError):
            return 0.0

    return await asyncio.to_thread(get_mtime)


async def save_persistent_cache_async() -> None:
    """Save the persistent cache asynchronously."""
    cache = get_persistent_cache()
    await asyncio.to_thread(cache.save)

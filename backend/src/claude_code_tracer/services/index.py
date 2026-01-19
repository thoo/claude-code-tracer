"""Background index service for project and session discovery.

This module provides a background indexer that decouples API response time from
filesystem scanning latency. Instead of scanning ~/.claude/projects/ on every
request, data is served from an in-memory index updated in the background.

Priority 4.1 implementation.
"""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any

import orjson
from loguru import logger

from ..utils.datetime import now_utc
from .database import PROJECTS_DIR, is_valid_uuid


@dataclass
class SessionMetadata:
    """Metadata for a session stored in the index."""

    session_id: str
    slug: str | None = None
    directory: str | None = None
    file_path: Path | None = None
    file_mtime: float = 0.0
    start_time: float | None = None  # Unix timestamp for sorting


@dataclass
class ProjectIndex:
    """Index data for a single project."""

    path_hash: str
    project_path: str = "Unknown"
    sessions: dict[str, SessionMetadata] = field(default_factory=dict)
    last_scanned: float = 0.0


class GlobalIndex:
    """Singleton class for the global project/session index.

    Thread-safe index that is populated on startup and periodically refreshed
    in the background.
    """

    _instance: "GlobalIndex | None" = None
    _lock = RLock()
    _projects: dict[str, ProjectIndex]
    _initialized: bool
    _scan_interval: int
    _background_task: "asyncio.Task[None] | None"

    def __new__(cls) -> "GlobalIndex":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._projects = {}
                cls._instance._initialized = False
                cls._instance._scan_interval = 30  # seconds
                cls._instance._background_task = None
            return cls._instance

    @property
    def projects(self) -> dict[str, ProjectIndex]:
        """Get all indexed projects."""
        with self._lock:
            return dict(self._projects)

    @property
    def is_initialized(self) -> bool:
        """Check if the index has been populated at least once."""
        with self._lock:
            return self._initialized

    def get_project(self, path_hash: str) -> ProjectIndex | None:
        """Get a specific project by its path hash."""
        with self._lock:
            return self._projects.get(path_hash)

    def get_sessions(self, path_hash: str) -> list[SessionMetadata]:
        """Get all sessions for a project."""
        with self._lock:
            project = self._projects.get(path_hash)
            if not project:
                return []
            return list(project.sessions.values())

    def scan_projects(self) -> None:
        """Scan the projects directory and update the index.

        This is the main scanning function that populates the index.
        It merges data from sessions-index.json files and filesystem scans.
        """
        if not PROJECTS_DIR.exists():
            logger.debug("Projects directory does not exist")
            return

        scan_start = now_utc().timestamp()
        new_projects: dict[str, ProjectIndex] = {}

        for project_dir in PROJECTS_DIR.iterdir():
            if not project_dir.is_dir() or project_dir.name == "-home-":
                continue

            path_hash = project_dir.name
            project_index = self._scan_project(project_dir, path_hash)
            if project_index:
                new_projects[path_hash] = project_index

        with self._lock:
            self._projects = new_projects
            self._initialized = True

        duration = now_utc().timestamp() - scan_start
        logger.debug(f"Index scan completed in {duration:.2f}s, found {len(new_projects)} projects")

    def _scan_project(self, project_dir: Path, path_hash: str) -> ProjectIndex | None:
        """Scan a single project directory."""
        try:
            project_index = ProjectIndex(path_hash=path_hash)
            project_index.last_scanned = now_utc().timestamp()

            # Try to get project path from sessions-index.json
            index_path = project_dir / "sessions-index.json"
            if index_path.exists():
                self._parse_sessions_index(index_path, project_index)

            # Scan filesystem for any sessions not in the index
            self._scan_filesystem_sessions(project_dir, project_index)

            return project_index

        except Exception as e:
            logger.debug(f"Error scanning project {path_hash}: {e}")
            return None

    def _parse_sessions_index(self, index_path: Path, project_index: ProjectIndex) -> None:
        """Parse sessions-index.json and populate the project index."""
        try:
            with open(index_path, "rb") as f:
                index_data = orjson.loads(f.read())
        except (orjson.JSONDecodeError, OSError) as e:
            logger.debug(f"Error reading sessions-index.json: {e}")
            return

        # Handle both new format (dict with entries) and old format (list)
        entries = []
        if isinstance(index_data, dict):
            entries = index_data.get("entries", [])
        elif isinstance(index_data, list):
            entries = index_data

        for entry in entries:
            if not isinstance(entry, dict):
                continue

            session_id = entry.get("sessionId") or entry.get("id", "")
            if not session_id or not is_valid_uuid(session_id):
                continue

            # Set project path from first valid entry
            if project_index.project_path == "Unknown":
                project_index.project_path = (
                    entry.get("projectPath") or entry.get("directory") or "Unknown"
                )

            session_meta = SessionMetadata(
                session_id=session_id,
                slug=entry.get("slug"),
                directory=entry.get("projectPath") or entry.get("directory"),
            )

            # Try to get file metadata
            session_file = PROJECTS_DIR / project_index.path_hash / f"{session_id}.jsonl"
            if session_file.exists():
                session_meta.file_path = session_file
                session_meta.file_mtime = session_file.stat().st_mtime

            project_index.sessions[session_id] = session_meta

    def _scan_filesystem_sessions(self, project_dir: Path, project_index: ProjectIndex) -> None:
        """Scan filesystem for sessions not in the index."""
        for jsonl_file in project_dir.glob("*.jsonl"):
            # Skip agent files
            if jsonl_file.name.startswith("agent-"):
                continue

            session_id = jsonl_file.stem
            if not is_valid_uuid(session_id):
                continue

            # Skip if already in index
            if session_id in project_index.sessions:
                continue

            session_meta = SessionMetadata(
                session_id=session_id,
                file_path=jsonl_file,
                file_mtime=jsonl_file.stat().st_mtime,
                directory=str(project_dir),
            )

            # If we still don't have a project path, try to extract from file
            if project_index.project_path == "Unknown":
                project_index.project_path = self._extract_project_path(jsonl_file)

            project_index.sessions[session_id] = session_meta

    def _extract_project_path(self, jsonl_file: Path) -> str:
        """Extract project path (cwd) from a JSONL file."""
        try:
            with open(jsonl_file, "rb") as f:
                for i, line in enumerate(f):
                    if i > 20:  # Only check first 20 lines
                        break
                    try:
                        data = orjson.loads(line)
                        if cwd := data.get("cwd"):
                            return cwd
                    except orjson.JSONDecodeError:
                        continue
        except OSError:
            pass
        return "Unknown"

    async def start_background_scanner(self) -> None:
        """Start the background scanning task."""
        # Do initial scan synchronously to ensure data is ready
        await asyncio.to_thread(self.scan_projects)

        # Start background refresh task
        self._background_task = asyncio.create_task(self._background_scan_loop())
        logger.info("Background index scanner started")

    async def stop_background_scanner(self) -> None:
        """Stop the background scanning task."""
        if self._background_task:
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass
            self._background_task = None
            logger.info("Background index scanner stopped")

    async def _background_scan_loop(self) -> None:
        """Background loop that periodically rescans the index."""
        while True:
            try:
                await asyncio.sleep(self._scan_interval)
                await asyncio.to_thread(self.scan_projects)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in background scan: {e}")
                # Continue running even on errors


# Singleton instance
_global_index: GlobalIndex | None = None


def get_global_index() -> GlobalIndex:
    """Get the global index singleton."""
    global _global_index
    if _global_index is None:
        _global_index = GlobalIndex()
    return _global_index


def get_projects_from_index() -> list[dict[str, Any]]:
    """Get all projects from the index.

    Returns data in the same format as database.list_projects() for compatibility.
    Falls back to database.list_projects() if index is not initialized.
    """
    index = get_global_index()

    if not index.is_initialized:
        # Fall back to direct scan
        from .database import list_projects

        return list_projects()

    projects = []
    for path_hash, project in index.projects.items():
        projects.append(
            {
                "path_hash": path_hash,
                "project_path": project.project_path,
                "session_count": len(project.sessions),
            }
        )

    return projects


def get_sessions_from_index(project_hash: str) -> list[dict[str, str | None]]:
    """Get sessions for a project from the index.

    Returns data in the same format as database.list_sessions() for compatibility.
    Falls back to database.list_sessions() if index is not initialized.
    """
    index = get_global_index()

    if not index.is_initialized:
        # Fall back to direct scan
        from .database import list_sessions

        return list_sessions(project_hash)

    sessions = index.get_sessions(project_hash)
    return [
        {
            "session_id": s.session_id,
            "slug": s.slug,
            "directory": s.directory or "",
        }
        for s in sessions
    ]

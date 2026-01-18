# Phase 4 Implementation Plan: Polish & Architecture

This document provides technical details for Phase 4 of the `claude-code-tracer` performance improvement plan. Phase 4 focuses on architectural polish, background processing, and standardization to ensure long-term maintainability and performance stability.

**Priorities:** 4.1, 4.2, 4.3, 4.5 from `improvement_plan.md`.

---

## 1. Background Index Builder (Priority 4.1)

### Goal
Decouple the API's response time from file system crawling latency. Instead of scanning `~/.claude/projects/` on every `/projects` or `/sessions` request, serve data from an in-memory index that is updated in the background.

### Implementation Details
- **New Service**: `backend/src/claude_code_tracer/services/index.py`
- **Mechanism**:
    1.  **Index Structure**:
        ```python
        @dataclass
        class ProjectIndex:
            path: Path
            sessions: dict[str, SessionMetadata]
            last_scanned: float

        class GlobalIndex:
            _projects: dict[str, ProjectIndex] = {}
            _lock: RLock
        ```
    2.  **Startup Scan**: On app startup, perform a full scan of the projects directory.
    3.  **Background Watcher**: Run a background thread (or `asyncio` task) that periodically (e.g., every 30s) re-scans for new/modified files.
    4.  **Integration**: Update `routers/sessions.py` to query `GlobalIndex` instead of calling `list_projects()` directly.

### Tasks
- [ ] Create `services/index.py` with `GlobalIndex` singleton.
- [ ] Implement `scan_projects()` to populate the index.
- [ ] Add `BackgroundScheduler` in `main.py` lifespan to run the scanner.
- [ ] Expose `get_projects_from_index()` and `get_sessions_from_index()` helpers.

---

## 2. Incremental Aggregates (Priority 4.3)

### Goal
Avoid re-calculating expensive aggregations (total tokens, costs) from scratch. Cache the results of closed/completed sessions and only process new data.

### Implementation Details
- **Storage**: `~/.claude/tracer-cache.json`
- **Mechanism**:
    1.  When `get_project_total_metrics` is called, check the cache.
    2.  For each session in the project:
        - If session is "completed" and cached, use cached values.
        - If session is "running" or not cached, parse the file (using the new optimization from Phase 3).
    3.  Update cache with new "completed" session data.

### Tasks
- [ ] Define cache schema (Project Hash -> Session ID -> {metrics, mtime}).
- [ ] Implement `PersistentCache` class in `services/cache.py` (extending Priority 3.6 work).
- [ ] Update `log_parser.py` to read/write to this cache for project-level metrics.

---

## 3. Async File I/O (Priority 4.2)

### Goal
Prevent filesystem operations from blocking the main event loop, keeping the API responsive even during heavy I/O.

### Implementation Details
- **Strategy**: Offload blocking I/O (like `glob`, `stat`, `open`) to a thread pool.
- **Tools**: `anyio.to_thread` or `asyncio.loop.run_in_executor`.
- **Key Areas**:
    - `list_projects` / `list_sessions` (file discovery).
    - `parse_session_summary` (file reading).

### Tasks
- [ ] Identify blocking calls in `services/database.py` and `services/log_parser.py`.
- [ ] Wrap these calls in async functions using `run_in_executor`.
- [ ] Update routers to await these new async service methods.

---

## 4. Datetime Standardization (Priority 4.5)

### Goal
Eliminate `TypeError: can't compare offset-naive and offset-aware datetimes` and ensure consistent UTC usage across the app.

### Implementation Details
- **New Utility**: `backend/src/claude_code_tracer/utils/datetime.py`
- **Function**:
    ```python
    from datetime import datetime, timezone

    def normalize_datetime(dt: datetime | str | None) -> datetime:
        """Always return a timezone-aware (UTC) datetime."""
        if dt is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if isinstance(dt, str):
            try:
                dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            except ValueError:
                return datetime.min.replace(tzinfo=timezone.utc)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    ```
- **Refactoring**: Replace all ad-hoc datetime parsing in `log_parser.py` and `routers/*.py` with this utility.

### Tasks
- [ ] Create `utils/datetime.py`.
- [ ] Scan codebase for `datetime.now()` (replace with `datetime.now(timezone.utc)`).
- [ ] Scan codebase for `datetime.fromisoformat()` and replace with `normalize_datetime`.

---

## 5. Affected Files

| File | Changes |
|------|---------|
| `services/index.py` | **NEW**: Background indexer logic. |
| `services/cache.py` | **NEW**: Persistent cache for aggregates. |
| `utils/datetime.py` | **NEW**: Datetime standardization helper. |
| `main.py` | Add background task startup/shutdown. |
| `services/database.py` | Add async wrappers for file ops. |
| `services/log_parser.py` | Integrate caching and standardized datetimes. |
| `routers/sessions.py` | Switch to using Index and Async service calls. |

---

## 6. Verification Plan

1.  **Index Consistency**: Verify that `GlobalIndex` accurately reflects the file system after adding/removing a dummy project folder.
2.  **Cache Hit Rate**: Monitor logs to ensure second requests to `/projects` hit the `tracer-cache.json` instead of reparsing.
3.  **Blocking Check**: Use `asyncio` debug mode to verify no blocking calls hold the loop for >100ms.
4.  **Timezone Tests**: Run existing tests to ensure no regression in timestamp comparisons.

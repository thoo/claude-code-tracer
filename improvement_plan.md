# Backend Performance Improvement Plan

This document outlines a comprehensive strategy to improve the performance of the `claude-code-tracer` backend. The current implementation relies heavily on on-the-fly parsing of JSONL files using DuckDB, which creates significant I/O overhead and latency as the dataset grows.

---

## Executive Summary

| Phase | Focus | Timeline | Expected Improvement |
|-------|-------|----------|---------------------|
| Phase 1 | Foundation (Caching & Connection) | Week 1 | 5-10x for repeated requests |
| Phase 2 | Core Fixes (N+1 & Glob Queries) | Week 2 | 15-30x for project listing |
| Phase 3 | Session Optimization (Views & Pagination) | Week 3 | 10x for message browsing |
| Phase 4 | Polish (Index Builder & Cleanup) | Week 4 | Consistency & maintainability |

---

## Priority 1: Quick Wins (High Impact, Low Effort)

These optimizations provide immediate performance gains with minimal code changes.

### 1.1 Persistent DuckDB Connection (Singleton)

| Attribute | Value |
|-----------|-------|
| **Effort** | 2-4 hours |
| **Impact** | ⭐⭐⭐⭐⭐ High |
| **Files** | `services/database.py`, `main.py` |

**Current State:**
A new `duckdb.connect(":memory:")` is created and destroyed for every single API call via the `get_connection()` context manager.

**Problem:**
- High overhead for initializing the DuckDB context repeatedly
- Loss of internal metadata and query plan cache that DuckDB builds up during execution
- Each connection re-initializes the JSON parser and schema inference

**Solution:**
```python
# services/database.py
class DuckDBPool:
    _instance: duckdb.DuckDBPyConnection | None = None
    _lock: threading.Lock = threading.Lock()

    @classmethod
    def get_connection(cls) -> duckdb.DuckDBPyConnection:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = duckdb.connect(":memory:")
        return cls._instance

    @classmethod
    def close(cls) -> None:
        if cls._instance is not None:
            cls._instance.close()
            cls._instance = None

# main.py - lifespan hook
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warm up connection
    conn = DuckDBPool.get_connection()
    conn.execute("SELECT 1")  # Warm up
    yield
    # Shutdown
    DuckDBPool.close()
```

---

### 1.2 Session Summary Caching

| Attribute | Value |
|-----------|-------|
| **Effort** | 3-5 hours |
| **Impact** | ⭐⭐⭐⭐⭐ High |
| **Files** | `services/log_parser.py` |

**Current State:**
`parse_session_summary()` runs 5+ DuckDB queries per session. Session summaries are re-calculated every time the project list is refreshed.

**Problem:**
Most sessions are "completed" and their log files will never change. Re-parsing them wastes CPU/IO.

**Solution:**
```python
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=500)
def _cached_session_summary(file_path: str, mtime: float) -> SessionSummary:
    """Cache key includes mtime so cache invalidates when file changes."""
    return _parse_session_summary_impl(file_path)

def parse_session_summary(project_hash: str, session_id: str) -> SessionSummary:
    path = get_session_path(project_hash, session_id)
    if not path.exists():
        raise FileNotFoundError(f"Session not found: {session_id}")
    mtime = path.stat().st_mtime
    return _cached_session_summary(str(path), mtime)
```

**Cache Invalidation:**
- Cache key is `(file_path, modification_timestamp)`
- If file's `mtime` changes, cache misses and re-parses
- LRU eviction handles memory limits automatically

---

### 1.3 Subagent File Index Cache

| Attribute | Value |
|-----------|-------|
| **Effort** | 2-3 hours |
| **Impact** | ⭐⭐⭐⭐ High |
| **Files** | `services/database.py` |

**Current State:**
`get_subagent_files_for_session()` opens and parses every `agent-*.jsonl` file to check if `sessionId` matches.

**Problem:**
For projects with many subagent files, this causes O(N) file opens just for discovery.

**Solution:**
```python
# Build index on startup or first access
_subagent_index: dict[str, dict[str, list[Path]]] = {}  # {project_hash: {session_id: [paths]}}
_subagent_index_mtime: float = 0

def _build_subagent_index(project_hash: str) -> dict[str, list[Path]]:
    """Build mapping of session_id -> subagent files."""
    index: dict[str, list[Path]] = defaultdict(list)
    project_dir = get_project_dir(project_hash)

    for agent_file in project_dir.glob("**/agent-*.jsonl"):
        with open(agent_file, "rb") as f:
            first_line = f.readline()
            if first_line:
                data = orjson.loads(first_line)
                session_id = data.get("sessionId", "")
                if session_id:
                    index[session_id].append(agent_file)

    return index

def get_subagent_files_for_session(project_hash: str, session_id: str) -> list[Path]:
    """Get subagent files using cached index."""
    if project_hash not in _subagent_index:
        _subagent_index[project_hash] = _build_subagent_index(project_hash)
    return _subagent_index[project_hash].get(session_id, [])
```

---

## Priority 2: Core Architecture Fixes (High Impact, Medium Effort)

These address fundamental architectural issues causing the worst performance problems.

### 2.1 Fix N+1 Query Pattern in `get_projects()`

| Attribute | Value |
|-----------|-------|
| **Effort** | 4-6 hours |
| **Impact** | ⭐⭐⭐⭐⭐ Critical |
| **Files** | `routers/sessions.py`, `services/log_parser.py` |

**Current State:**
```python
# Current: O(N*M) queries where N=projects, M=sessions per project
for project in projects:
    for session_id in session_ids:
        summary = parse_session_summary(project_hash, session_id)  # 5+ queries each!
```

**Problem:**
With 50 projects × 20 sessions = 1000 session summaries × 5 queries = **5000+ DuckDB queries**.

**Solution:**
Use DuckDB's globbing to aggregate across all files in a single query:

```sql
-- Single query replaces thousands of individual queries
SELECT
    regexp_extract(filename, '/([^/]+)/[^/]+\.jsonl$', 1) as project_hash,
    COUNT(DISTINCT regexp_extract(filename, '/([^/]+)\.jsonl$', 1)) as session_count,
    SUM(COALESCE(message.usage.input_tokens, 0)) as total_input_tokens,
    SUM(COALESCE(message.usage.output_tokens, 0)) as total_output_tokens,
    SUM(COALESCE(message.usage.cache_creation_input_tokens, 0)) as total_cache_creation,
    SUM(COALESCE(message.usage.cache_read_input_tokens, 0)) as total_cache_read
FROM read_json_auto(
    '~/.claude/projects/*/*.jsonl',
    filename=true,
    maximum_object_size=104857600,
    union_by_name=true
)
WHERE type = 'assistant'
  AND message.usage IS NOT NULL
GROUP BY project_hash;
```

---

### 2.2 Glob-based Aggregate Metrics

| Attribute | Value |
|-----------|-------|
| **Effort** | 4-6 hours |
| **Impact** | ⭐⭐⭐⭐⭐ Critical |
| **Files** | `services/log_parser.py`, `services/queries.py` |

**Current State:**
`get_aggregate_metrics()` loops through projects and sessions, executing individual queries.

**Solution:**
Create new query templates that use glob patterns:

```python
# services/queries.py
AGGREGATE_METRICS_GLOB_QUERY = """
SELECT
    SUM(COALESCE(message.usage.input_tokens, 0)) as total_input,
    SUM(COALESCE(message.usage.output_tokens, 0)) as total_output,
    SUM(COALESCE(message.usage.cache_creation_input_tokens, 0)) as cache_creation,
    SUM(COALESCE(message.usage.cache_read_input_tokens, 0)) as cache_read,
    COUNT(DISTINCT message.id) as message_count
FROM read_json_auto(
    '{glob_pattern}',
    maximum_object_size=104857600,
    union_by_name=true,
    ignore_errors=true
)
WHERE type = 'assistant' AND message.usage IS NOT NULL
"""

# Usage
def get_global_metrics() -> AggregateMetrics:
    pattern = str(CLAUDE_DIR / "projects/*/*.jsonl")
    result = conn.execute(AGGREGATE_METRICS_GLOB_QUERY.format(glob_pattern=pattern)).fetchone()
    return AggregateMetrics(**result)
```

---

### 2.3 Temporary Session Views

| Attribute | Value |
|-----------|-------|
| **Effort** | 3-4 hours |
| **Impact** | ⭐⭐⭐⭐ High |
| **Files** | `services/database.py`, `routers/sessions.py` |

**Current State:**
When viewing a session, the frontend requests `/messages`, `/metrics`, `/tools` - each runs `read_json_auto()` separately, parsing the file 3 times.

**Solution:**
Create a temporary view once per session context:

```python
def create_session_view(conn: duckdb.DuckDBPyConnection, session_path: Path) -> str:
    """Create a temp view for the session, return view name."""
    view_name = f"session_{hash(str(session_path)) % 10000}"
    conn.execute(f"""
        CREATE OR REPLACE TEMPORARY VIEW {view_name} AS
        SELECT * FROM read_json_auto(
            '{session_path}',
            maximum_object_size=104857600,
            union_by_name=true
        )
    """)
    return view_name

# Then queries use the view name instead of read_json_auto()
def get_session_metrics(view_name: str) -> SessionMetrics:
    return conn.execute(f"SELECT ... FROM {view_name} WHERE ...").fetchone()
```

---

### 2.4 Batch Subagent Token Aggregation

| Attribute | Value |
|-----------|-------|
| **Effort** | 3-4 hours |
| **Impact** | ⭐⭐⭐⭐ High |
| **Files** | `services/log_parser.py` |

**Current State:**
`_accumulate_subagent_data()` loops through subagent files, executing queries for each.

**Solution:**
Pass all file paths to a single `read_json_auto()` call:

```python
def get_session_with_subagents_metrics(
    session_path: Path,
    subagent_paths: list[Path]
) -> TokenUsage:
    """Get combined metrics for session + all subagents in one query."""
    all_paths = [str(session_path)] + [str(p) for p in subagent_paths]

    query = f"""
    SELECT
        SUM(COALESCE(message.usage.input_tokens, 0)) as input_tokens,
        SUM(COALESCE(message.usage.output_tokens, 0)) as output_tokens,
        SUM(COALESCE(message.usage.cache_creation_input_tokens, 0)) as cache_creation,
        SUM(COALESCE(message.usage.cache_read_input_tokens, 0)) as cache_read
    FROM read_json_auto(
        {all_paths},
        maximum_object_size=104857600,
        union_by_name=true
    )
    WHERE type = 'assistant' AND message.usage IS NOT NULL
    """
    return conn.execute(query).fetchone()
```

---

## Priority 3: Query Optimizations (Medium Impact, Medium Effort)

### 3.1 Keyset Pagination

| Attribute | Value |
|-----------|-------|
| **Effort** | 4-6 hours |
| **Impact** | ⭐⭐⭐ Medium |
| **Files** | `services/queries.py`, `routers/sessions.py` |

**Current State:**
```sql
-- Current: Full scan + sort + row numbering
WITH numbered AS (
    SELECT *, ROW_NUMBER() OVER (ORDER BY timestamp) as rn
    FROM (... 5 UNION queries ...)
)
SELECT * FROM numbered WHERE rn BETWEEN {offset} AND {offset + limit}
```

**Problem:**
For 100k+ rows, this sorts the entire dataset before returning 50 rows.

**Solution:**
Use keyset (cursor-based) pagination:

```sql
-- After first page, use cursor
SELECT * FROM (... UNION queries ...)
WHERE timestamp > '{last_timestamp}'
  AND (timestamp > '{last_timestamp}' OR uuid > '{last_uuid}')
ORDER BY timestamp, uuid
LIMIT {limit}
```

---

### 3.2 Lazy Count / Has-More Flag

| Attribute | Value |
|-----------|-------|
| **Effort** | 2-3 hours |
| **Impact** | ⭐⭐⭐ Medium |
| **Files** | `routers/sessions.py`, `models/responses.py` |

**Current State:**
Every paginated request runs a separate `COUNT(*)` query.

**Solution:**
```python
# Instead of exact count, fetch limit+1 rows
def get_messages_paginated(limit: int, cursor: str | None):
    rows = fetch_rows(limit + 1, cursor)
    has_more = len(rows) > limit
    return {
        "items": rows[:limit],
        "has_more": has_more,
        "next_cursor": rows[limit - 1].cursor if has_more else None
    }
```

---

### 3.3 Pre-filter Before UNION

| Attribute | Value |
|-----------|-------|
| **Effort** | 3-4 hours |
| **Impact** | ⭐⭐⭐ Medium |
| **Files** | `services/queries.py` |

**Current State:**
Filters are applied after the UNION in an outer wrapper.

**Solution:**
Push `WHERE` clauses into each UNION branch:

```sql
-- Before: Filter after UNION
SELECT * FROM (
    SELECT ... FROM source1
    UNION ALL
    SELECT ... FROM source2
) WHERE type = 'tool_use'

-- After: Filter in each branch (enables predicate pushdown)
SELECT * FROM (
    SELECT ... FROM source1 WHERE type = 'tool_use'
    UNION ALL
    SELECT ... FROM source2 WHERE type = 'tool_use'
)
```

---

## Priority 4: Additional Improvements (Previously Missing)

### 4.1 Background Index Builder

| Attribute | Value |
|-----------|-------|
| **Effort** | 6-8 hours |
| **Impact** | ⭐⭐⭐⭐ High |
| **Files** | `services/index.py` (new), `main.py` |

**Description:**
On startup, scan all projects once and build an in-memory index of sessions + metadata. Serve `/projects` from index instead of scanning filesystem.

```python
@dataclass
class SessionIndex:
    projects: dict[str, ProjectInfo]
    sessions: dict[str, dict[str, SessionInfo]]  # {project_hash: {session_id: info}}
    last_updated: datetime

async def build_index() -> SessionIndex:
    """Build index in background thread."""
    # Scan filesystem once
    # Parse session-index.json files
    # Build lightweight metadata (no token counting)
    pass

# Refresh periodically or on file change
```

---

### 4.2 Async File I/O

| Attribute | Value |
|-----------|-------|
| **Effort** | 8-12 hours |
| **Impact** | ⭐⭐⭐ Medium |
| **Files** | `services/database.py`, `services/log_parser.py` |

**Description:**
Current implementation is synchronous. Use `aiofiles` or thread pool for concurrent file discovery.

```python
import asyncio
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=4)

async def get_projects_async() -> list[Project]:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(executor, get_projects_sync)
```

---

### 4.3 Incremental Aggregates

| Attribute | Value |
|-----------|-------|
| **Effort** | 6-8 hours |
| **Impact** | ⭐⭐⭐⭐ High |
| **Files** | `services/aggregates.py` (new) |

**Description:**
Store running totals in a lightweight cache file. Only parse new JSONL lines since last aggregation.

```python
# ~/.claude/tracer-cache.json
{
    "projects": {
        "abc123": {
            "total_tokens": 150000,
            "total_cost": 4.52,
            "last_processed_line": 1523,
            "file_size_at_process": 2048576
        }
    }
}
```

---

### 4.4 Response Streaming

| Attribute | Value |
|-----------|-------|
| **Effort** | 4-6 hours |
| **Impact** | ⭐⭐⭐ Medium |
| **Files** | `routers/sessions.py` |

**Description:**
For large message lists, stream JSON responses instead of building full list in memory.

```python
from fastapi.responses import StreamingResponse

@router.get("/sessions/{hash}/{id}/messages/stream")
async def stream_messages(hash: str, id: str):
    async def generate():
        yield '{"items": ['
        first = True
        for msg in iterate_messages(hash, id):
            if not first:
                yield ','
            yield orjson.dumps(msg).decode()
            first = False
        yield ']}'

    return StreamingResponse(generate(), media_type="application/json")
```

---

### 4.5 Datetime Timezone Standardization

| Attribute | Value |
|-----------|-------|
| **Effort** | 2-3 hours |
| **Impact** | ⭐⭐ Low |
| **Files** | `services/log_parser.py`, `utils/datetime.py` (new) |

**Description:**
Standardize timezone handling to prevent `TypeError: can't compare offset-naive and offset-aware datetimes`.

```python
# utils/datetime.py
from datetime import UTC, datetime

def normalize_datetime(dt: datetime | str | None) -> datetime:
    """Ensure datetime is timezone-aware UTC."""
    if dt is None:
        return datetime.min.replace(tzinfo=UTC)
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)
```

---

### 4.6 Connection Warmup

| Attribute | Value |
|-----------|-------|
| **Effort** | 1-2 hours |
| **Impact** | ⭐⭐⭐ Medium |
| **Files** | `main.py` |

**Description:**
On app startup, run queries to initialize DuckDB's JSON parser and schema inference.

```python
async def warmup_duckdb():
    """Pre-warm DuckDB caches."""
    conn = DuckDBPool.get_connection()
    # Warm up JSON parser
    conn.execute("SELECT * FROM read_json_auto('{}') LIMIT 0".format(
        str(next(CLAUDE_DIR.glob("projects/*/*.jsonl"), ""))
    ))
```

---

## Priority 5: Future Optimizations (High Effort, Deferred)

### 5.1 Parquet Conversion

| Attribute | Value |
|-----------|-------|
| **Effort** | 12-16 hours |
| **Impact** | ⭐⭐⭐⭐ High |

Convert completed session JSONLs to Parquet for columnar reads. Expected 5-10x faster for analytics queries.

### 5.2 Persistent DuckDB File

| Attribute | Value |
|-----------|-------|
| **Effort** | 8-12 hours |
| **Impact** | ⭐⭐⭐⭐ High |

Use file-backed DuckDB (`~/.claude/tracer.duckdb`) with materialized views instead of in-memory.

### 5.3 File Change Watcher

| Attribute | Value |
|-----------|-------|
| **Effort** | 8-10 hours |
| **Impact** | ⭐⭐⭐ Medium |

Use `watchdog` library to detect JSONL changes and invalidate caches proactively.

### 5.4 Worker Process Pool

| Attribute | Value |
|-----------|-------|
| **Effort** | 10-15 hours |
| **Impact** | ⭐⭐⭐ Medium |

For heavy aggregations, offload to background workers (Celery/RQ) and return job IDs.

---

## Implementation Roadmap

### Phase 1: Foundation (Week 1)

| Day | Task | Priority |
|-----|------|----------|
| 1-2 | Persistent DuckDB Connection | 1.1 |
| 2-3 | Subagent File Index Cache | 1.3 |
| 3-4 | Session Summary Caching | 1.2 |
| 5 | Connection Warmup + Testing | 4.6 |

### Phase 2: Core Fixes (Week 2)

| Day | Task | Priority |
|-----|------|----------|
| 1-2 | Fix N+1 in get_projects() | 2.1 |
| 3-4 | Glob-based Aggregations | 2.2 |
| 5 | Batch Subagent Token Aggregation | 2.4 |

### Phase 3: Session Optimization (Week 3)

| Day | Task | Priority |
|-----|------|----------|
| 1-2 | Temporary Session Views | 2.3 |
| 3-4 | Keyset Pagination | 3.1 |
| 5 | Lazy Count + Pre-filter UNION | 3.2, 3.3 |

### Phase 4: Polish (Week 4)

| Day | Task | Priority |
|-----|------|----------|
| 1-2 | Background Index Builder | 4.1 |
| 3-4 | Datetime Standardization | 4.5 |
| 5 | Performance testing + documentation | - |

---

## Expected Performance Gains

| Endpoint | Current | Expected | Improvement |
|----------|---------|----------|-------------|
| `GET /api/projects` (50 projects, 500 sessions) | 15-30s | 0.5-1s | **15-30x** |
| `GET /api/sessions/{}/messages` (10k rows) | 3-5s | 0.3-0.5s | **10x** |
| `GET /api/metrics/aggregate` | 10-20s | 1-2s | **10x** |
| Session detail page (3 parallel requests) | 6-9s | 0.5-1s | **6-9x** |
| Memory usage (100 concurrent users) | 2-4GB | 500MB-1GB | **4x** |

---

## Observability Recommendations

1. **Add Metrics**: Use `prometheus-fastapi-instrumentator` to track query latency, cache hit rates
2. **Health Check**: Add `/health` endpoint that verifies DuckDB connection and file access
3. **Slow Query Logging**: Log queries taking >500ms for optimization candidates
4. **Rate Limiting**: Consider rate limiting heavy endpoints like `/projects`

---

## Testing Strategy

1. **Benchmark Suite**: Create scripts to measure endpoint latency before/after changes
2. **Load Testing**: Use `locust` or `k6` to simulate concurrent users
3. **Regression Tests**: Ensure query results remain identical after optimization
4. **Cache Validation**: Test cache invalidation on file changes

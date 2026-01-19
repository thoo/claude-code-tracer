# Phase 3 Implementation Plan: Session Optimization

This document provides technical details for Phase 3 of the `claude-code-tracer` performance improvement plan. Phase 3 focuses on optimizing the session detail view, specifically message retrieval and filtering.

**Last Updated**: 2025-01-18

---

## Implementation Status Overview

| Priority | Feature | Status | Impact | Effort |
|----------|---------|--------|--------|--------|
| 2.3 | Temporary Session Views | ✅ Complete | Medium | Low |
| 3.1 | Keyset Pagination | ✅ Complete | High | Medium |
| 3.2 | Lazy Counting | ✅ Complete | Medium | Low |
| 3.3 | Query Pre-filtering | ❌ Not Started | Medium | Medium |
| 3.4 | Response Streaming | ❌ Not Started | High | Medium |
| 3.5 | Message Content Lazy Loading | ✅ Partial (MessageSummary model added) | High | Low |
| 3.6 | Query Result Caching | ✅ Complete | Medium | Medium |

---

## 1. Temporary Session Views (Priority 2.3)

### Goal
Reduce redundant I/O by parsing a session's JSONL file once per "request cluster" (e.g., when a user opens a session and the frontend fires 3-5 parallel requests for messages, metrics, tools, etc.).

### Current Status: ✅ Complete

**Completed:**
- [x] Implemented `get_or_create_session_view()` in `database.py`
- [x] Implemented `invalidate_session_view()` for cache invalidation
- [x] Implemented `cleanup_stale_views()` with 5-minute TTL
- [x] Implemented `get_session_view_query()` fallback helper
- [x] Added cleanup on application shutdown in `main.py`
- [x] Refactored `queries.py` with V2 queries using `{source}` placeholder
- [x] Updated `log_parser.py` functions to use session views
- [x] Updated `routers/sessions.py` all endpoints to use session views

### Implementation Details

**Location**: `backend/src/claude_code_tracer/services/database.py`

**Current Implementation:**
```python
# Session view cache: {session_path: (view_name, created_time, file_mtime)}
_session_views: dict[str, tuple[str, float, float]] = {}
SESSION_VIEW_TTL = 300  # 5 minutes

def get_or_create_session_view(session_path: Path) -> str:
    """Get or create a temporary view for a session file."""
    # ... implementation exists

def get_session_view_query(session_path: Path) -> str:
    """Get a query source - either view name or read_json_auto fallback."""
    # ... implementation exists
```

**Next Steps - Query Refactoring:**

1. Update query templates in `queries.py`:
```python
# Before
MESSAGES_COMPREHENSIVE_QUERY = f"""
...
FROM read_json_auto('{{path}}', {_JSON_OPTS})
...
"""

# After
MESSAGES_COMPREHENSIVE_QUERY = f"""
...
FROM {{source}}
...
"""
```

2. Update callers to use session views:
```python
# In routers/sessions.py
from ..services.database import get_session_view_query

source = get_session_view_query(session_path)
query = MESSAGES_COMPREHENSIVE_QUERY.format(source=source, ...)
```

---

## 2. Keyset (Cursor-based) Pagination (Priority 3.1)

### Goal
Avoid the performance degradation of `OFFSET` pagination on large datasets. DuckDB performs a full sort and scan to reach high offsets.

### Current Status: ✅ Complete

**Completed:**
- [x] Added `cursor` parameter to `get_session_messages` endpoint
- [x] Implemented cursor encoding/decoding (base64 of `timestamp|uuid`)
- [x] Updated `MessageListResponse` with `next_cursor` and `has_more` fields
- [x] Keyset comparison uses `(timestamp, uuid) > (cursor_ts, cursor_uuid)` for efficient filtering
- [x] Maintains backward compatibility with page-based pagination

### Problem Analysis
Current pagination in `get_session_messages()`:
```python
offset = (page - 1) * per_page
# ...
paginated_query = f"""
WITH comprehensive AS ({query})
SELECT * FROM comprehensive
WHERE row_num > {offset}
LIMIT {per_page}
"""
```

**Issues:**
- OFFSET requires scanning all rows up to the offset
- Page 100 with 50 items/page means scanning 5000 rows
- Gets progressively slower as users navigate deeper

### Implementation Details

**Location**: `backend/src/claude_code_tracer/routers/sessions.py` and `services/queries.py`

**Mechanism:**
1. Clients pass a `cursor` (encoded `timestamp|uuid`) instead of `page`
2. The SQL query uses the cursor for efficient filtering:
```sql
SELECT * FROM comprehensive_messages
WHERE (timestamp, uuid) > ('{ts_cursor}', '{uuid_cursor}')
ORDER BY timestamp, uuid
LIMIT {limit + 1}
```
3. The backend provides a `next_cursor` in the response if more results are available

### Tasks
- [ ] Update `MessageListResponse` model to include `next_cursor` and `has_more`
- [ ] Add cursor encoding/decoding utilities (base64 of `timestamp|uuid`)
- [ ] Modify `get_session_messages` to accept `cursor` parameter (keep `page` for backward compatibility)
- [ ] Update `MESSAGES_COMPREHENSIVE_QUERY` to support keyset comparison
- [ ] Update frontend to use cursor-based navigation

### API Changes

**Before:**
```
GET /sessions/{project}/{session}/messages?page=5&per_page=50
```

**After:**
```
GET /sessions/{project}/{session}/messages?cursor=MjAyNC0wMS0wMVQxMjowMDowMFp8YWJjMTIz&limit=50
```

**Response:**
```json
{
  "messages": [...],
  "next_cursor": "MjAyNC0wMS0wMVQxMjowNTowMFp8ZGVmNDU2",
  "has_more": true
}
```

---

## 3. Lazy Counting & Has-More Flag (Priority 3.2)

### Goal
Eliminate the expensive `SELECT COUNT(*)` query required for traditional pagination.

### Current Status: ✅ Complete

**Completed:**
- [x] Implemented `limit + 1` fetching pattern in `get_session_messages`
- [x] Added `has_more` field to `MessageListResponse`
- [x] COUNT query only runs on first page when needed for UI
- [x] Subsequent pages estimate total based on current position

### Problem Analysis
Current implementation runs a separate count query:
```python
count_query = f"""
WITH comprehensive AS ({query})
SELECT COUNT(*) FROM comprehensive
"""
total = conn.execute(count_query).fetchone()[0]
```

This is expensive because it:
- Re-parses the entire JSONL file
- Executes the full comprehensive query logic
- Only to return a single number

### Implementation Details

**Mechanism:**
1. Request `limit + 1` rows from the database
2. If the database returns `limit + 1` rows, set `has_more = true`
3. Use the `limit`-th row's cursor for `next_cursor`
4. Return only the first `limit` rows to the client

**Code Example:**
```python
# Request one extra row
result = conn.execute(query).fetchmany(limit + 1)

has_more = len(result) > limit
messages = result[:limit]  # Return only requested amount

if has_more:
    last_msg = messages[-1]
    next_cursor = encode_cursor(last_msg.timestamp, last_msg.uuid)
```

### Tasks
- [ ] Remove `count_query` execution from `get_session_messages`
- [ ] Implement `limit + 1` fetching pattern
- [ ] Update response model to remove `total` and `total_pages` (or make optional)
- [ ] Update frontend to handle cursor-based "Load More" instead of page numbers

---

## 4. Query Pre-filtering (Priority 3.3)

### Goal
Enable DuckDB's predicate pushdown by applying filters *before* the `UNION ALL` operation in the comprehensive message query.

### Current Status: ❌ Not Started

### Problem Analysis
Current `MESSAGES_COMPREHENSIVE_QUERY` structure:
```sql
WITH assistant_messages AS (...),
     user_messages AS (...),
     tool_result_messages AS (...),
     subagent_messages AS (...)
SELECT * FROM (
    SELECT * FROM assistant_messages
    UNION ALL
    SELECT * FROM user_messages
    UNION ALL
    ...
)
WHERE {filters}  -- Filters applied AFTER union
```

This means ALL message types are processed even when filtering for just one type.

### Implementation Details

**Location**: `backend/src/claude_code_tracer/services/queries.py`

**Approach 1: Conditional CTE Generation**
Build query dynamically based on filters:
```python
def build_messages_query(type_filter: str | None = None, ...):
    ctes = []

    if type_filter is None or type_filter == 'assistant':
        ctes.append(ASSISTANT_MESSAGES_CTE)
    if type_filter is None or type_filter == 'user':
        ctes.append(USER_MESSAGES_CTE)
    # ...

    return f"""
    WITH {', '.join(ctes)}
    SELECT * FROM ({' UNION ALL '.join(cte_names)})
    """
```

**Approach 2: Filter Injection into CTEs**
Pass filter fragments into each CTE:
```python
ASSISTANT_MESSAGES_CTE = """
assistant_messages AS (
    SELECT ...
    FROM {source}
    WHERE type = 'assistant'
      {additional_filters}  -- Injected per-CTE filters
)
"""
```

### Tasks
- [ ] Break `MESSAGES_COMPREHENSIVE_QUERY` into modular CTE templates
- [ ] Create query builder function that assembles CTEs based on filters
- [ ] Add type-specific filter injection
- [ ] Benchmark improvement on filtered queries

---

## 5. Response Streaming (Priority 3.4) - NEW

### Goal
Stream large message lists to the client instead of buffering the entire response, reducing time-to-first-byte and memory usage.

### Current Status: ❌ Not Started

### Problem Analysis
Current implementation:
```python
result = conn.execute(query).fetchall()  # Loads ALL into memory
messages = [_parse_message_row(row) for row in result]  # Processes ALL
return MessageListResponse(messages=messages, ...)  # Serializes ALL
```

For a session with 5000 messages, this means:
- Loading 5000 rows into memory
- Processing 5000 rows before sending anything
- Client waits for entire response

### Implementation Details

**Location**: `backend/src/claude_code_tracer/routers/sessions.py`

**Mechanism**: Use FastAPI's `StreamingResponse` with newline-delimited JSON (NDJSON):

```python
from fastapi.responses import StreamingResponse

async def stream_messages(session_path: Path, ...):
    with get_connection() as conn:
        cursor = conn.execute(query)

        # Stream header
        yield '{"has_more": true}\n'

        # Stream messages one by one
        while row := cursor.fetchone():
            message = _parse_message_row(row)
            yield message.model_dump_json() + '\n'

@router.get("/sessions/{project}/{session}/messages/stream")
async def get_session_messages_stream(...):
    return StreamingResponse(
        stream_messages(session_path, ...),
        media_type="application/x-ndjson"
    )
```

### Tasks
- [ ] Add streaming endpoint `/messages/stream`
- [ ] Implement NDJSON streaming generator
- [ ] Update frontend to consume streaming responses
- [ ] Add progress indicator for streaming loads

---

## 6. Message Content Lazy Loading (Priority 3.5) - NEW

### Goal
Return lightweight message metadata first, then load full content on demand. Most users don't need full content for all messages in the list view.

### Current Status: ✅ Partial

**Completed:**
- [x] Created `MessageSummary` model with minimal fields (uuid, type, timestamp, preview, model, tool_names, has_error)

**Remaining:**
- [ ] Add SQL query that extracts only metadata (no content parsing)
- [ ] Add `expand` parameter to messages endpoint
- [ ] Update frontend to use summary view for list, full view for detail

### Problem Analysis
Current message response includes full content:
```python
class MessageResponse(BaseModel):
    uuid: str
    type: str
    timestamp: datetime
    content: str | None  # Can be very large (tool results, code)
    model: str | None
    tokens: TokenUsage
    tools: list[ToolUse]
    tool_names: str
    # ...
```

For list view, we truncate to 500 chars but still:
- Parse full JSON content from DuckDB
- Transfer larger payloads than needed

### Implementation Details

**Approach 1: Summary-only List Endpoint**
```python
class MessageSummary(BaseModel):
    uuid: str
    type: str
    timestamp: datetime
    preview: str  # First 100 chars
    model: str | None
    tool_names: str
    has_error: bool

@router.get("/messages/summaries")
async def get_message_summaries(...) -> list[MessageSummary]:
    # Lightweight query that only extracts metadata
    pass
```

**Approach 2: Expand-on-demand**
Keep current endpoint but add `expand=false` parameter:
```
GET /messages?expand=false  # Returns summaries
GET /messages?expand=true   # Returns full content (current behavior)
GET /messages/{uuid}        # Returns single message with full content
```

### Tasks
- [ ] Create `MessageSummary` model with minimal fields
- [ ] Add SQL query that extracts only metadata (no content parsing)
- [ ] Add `expand` parameter to messages endpoint
- [ ] Update frontend to use summary view for list, full view for detail

---

## 7. Query Result Caching (Priority 3.6) - NEW

### Goal
Cache expensive query results (tool usage stats, error counts, filter options) that don't change within a session.

### Current Status: ✅ Complete

**Completed:**
- [x] Created `services/cache.py` with file-mtime-based caching
- [x] Implemented caching for `/tools` endpoint (`cache_tool_usage`)
- [x] Implemented caching for `/metrics` endpoint (`cache_metrics`)
- [x] Implemented caching for `/subagents` endpoint (`cache_subagents`)
- [x] Implemented caching for `/messages/filters` endpoint (`cache_filter_options`)
- [x] Automatic cache invalidation when file mtime changes
- [x] Added `clear_all_caches()` and `get_cache_stats()` utilities

### Problem Analysis
Several endpoints return data that's static for a given session file:
- `/messages/filters` - tool names, error count
- `/tools` - tool usage statistics
- `/metrics` - session metrics

These get re-queried every time the user navigates, but the data only changes if the session file changes.

### Implementation Details

**Location**: `backend/src/claude_code_tracer/services/cache.py` (new file)

**Mechanism**: File-mtime-based caching with TTL:

```python
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=200)
def _cached_tool_stats(path_str: str, mtime: float) -> ToolUsageResponse:
    """Cache tool stats keyed by path and mtime."""
    # ... query implementation

def get_session_tool_stats(session_path: Path) -> ToolUsageResponse:
    mtime = session_path.stat().st_mtime
    return _cached_tool_stats(str(session_path), mtime)
```

**What to Cache:**
| Endpoint | Cache Key | TTL |
|----------|-----------|-----|
| `/tools` | `{path}:{mtime}` | Until mtime changes |
| `/metrics` | `{path}:{mtime}` | Until mtime changes |
| `/messages/filters` | `{path}:{mtime}` | Until mtime changes |
| `/subagents` | `{path}:{mtime}` | Until mtime changes |

### Tasks
- [ ] Create caching utility module
- [ ] Apply caching to tool usage endpoint
- [ ] Apply caching to metrics endpoint
- [ ] Apply caching to filter options endpoint
- [ ] Add cache invalidation on file change detection

---

## 8. DuckDB Connection Pooling Improvements (Priority 3.7) - NEW

### Goal
Optimize DuckDB connection handling for concurrent requests.

### Current Status: ✅ Basic Implementation Exists

### Current Implementation
```python
class DuckDBPool:
    _instance: ClassVar[duckdb.DuckDBPyConnection | None] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()

    @classmethod
    def get_connection(cls) -> duckdb.DuckDBPyConnection:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = duckdb.connect(":memory:")
        return cls._instance
```

### Potential Improvements

**1. Connection per Thread**
DuckDB connections are not thread-safe. Current single connection may cause issues under load:
```python
_local = threading.local()

def get_connection() -> duckdb.DuckDBPyConnection:
    if not hasattr(_local, 'conn'):
        _local.conn = duckdb.connect(":memory:")
    return _local.conn
```

**2. Read-only Connection Sharing**
For read-only queries, DuckDB supports concurrent access:
```python
# Main connection for writes
_write_conn = duckdb.connect(":memory:")

# Read connections share catalog
def get_read_connection():
    return _write_conn.cursor()
```

### Tasks
- [ ] Benchmark current connection handling under concurrent load
- [ ] Implement thread-local connections if needed
- [ ] Add connection health checks
- [ ] Consider connection timeout/recycling

---

## 9. Frontend Optimizations (Priority 3.8) - NEW

### Goal
Complement backend optimizations with frontend improvements.

### Recommendations

**1. Virtual Scrolling for Message List**
Instead of paginating, use virtual scrolling to render only visible messages:
- Libraries: `react-virtual`, `react-window`
- Load messages in chunks as user scrolls
- Pairs well with cursor-based backend pagination

**2. Optimistic UI Updates**
- Show loading skeletons immediately
- Cache previously loaded sessions in frontend state
- Pre-fetch adjacent pages/cursors

**3. Request Deduplication**
- Dedupe concurrent requests for same resource
- Cancel in-flight requests when navigating away
- Use SWR or React Query for automatic caching

**4. Lazy Load Session Details**
- Load session list first (lightweight)
- Load session details only when expanded
- Progressive enhancement

### Tasks
- [ ] Implement virtual scrolling for messages
- [ ] Add frontend caching layer (React Query/SWR)
- [ ] Add request cancellation on navigation
- [ ] Implement skeleton loading states

---

## 10. Affected Files Summary

| File | Changes | Status |
|------|---------|--------|
| `models/responses.py` | Added `MessageSummary`, updated `MessageListResponse` with cursor fields (`next_cursor`, `has_more`) | ✅ Done |
| `services/database.py` | View management (existing), `get_session_view_query()` helper | ✅ Done |
| `services/queries.py` | Added V2 queries with `{source}` placeholder, `make_source_query()` helper | ✅ Done |
| `services/log_parser.py` | Updated all functions to use V2 queries with session views | ✅ Done |
| `services/cache.py` | NEW - Query result caching utilities (tool, metrics, filters, subagents) | ✅ Done |
| `routers/sessions.py` | Cursor pagination, caching integration, session view usage | ✅ Done |

---

## 11. Verification Plan

### Performance Benchmarks
1. **Large Session Test**: Measure response time for `GET /messages` on sessions with 1K, 5K, 10K entries
2. **Deep Pagination Test**: Compare page 1 vs page 100 response times (before/after keyset)
3. **Concurrent Request Test**: Fire 10 parallel requests for same session, verify view reuse
4. **Filtered Query Test**: Measure `type=assistant` filter with and without pre-filtering

### Correctness Tests
1. **Cursor Stability**: Verify cursor produces consistent results across requests
2. **Filter Accuracy**: Ensure pre-filtering produces same results as post-filtering
3. **View Consistency**: Verify session view invalidates when file changes
4. **Cache Invalidation**: Verify cached results update when session file modified

### Resource Monitoring
1. **Memory Usage**: Monitor DuckDB memory with many active session views
2. **Connection Count**: Verify connection pooling under load
3. **View Cleanup**: Confirm stale views are dropped after TTL

---

## 12. Implementation Priority Order

Based on impact/effort ratio, recommended implementation order:

1. **Phase 3A - Quick Wins** (1-2 days)
   - Complete session view integration (use existing infrastructure)
   - Implement lazy counting (`limit + 1` pattern)
   - Add query result caching for static endpoints

2. **Phase 3B - High Impact** (2-3 days)
   - Implement keyset pagination
   - Add message summary/lazy loading endpoint
   - Update frontend for cursor-based navigation

3. **Phase 3C - Polish** (2-3 days)
   - Response streaming for large sessions
   - Query pre-filtering optimization
   - Frontend virtual scrolling

4. **Phase 3D - Infrastructure** (1-2 days)
   - Connection pooling improvements
   - Comprehensive benchmarking
   - Documentation and monitoring

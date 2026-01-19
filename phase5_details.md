# Phase 5 Implementation Plan: Advanced Optimization & Scalability

This document outlines the strategy for Phase 5, focusing on handling very large datasets (100k+ messages), ensuring real-time responsiveness through event-based updates, and further reducing memory footprint via streaming and columnar storage.

**Priorities:** 3.3, 3.4, 5.1, 5.2, 5.3, 5.4 from `improvement_plan.md`.

---

## 1. Response Streaming (Priority 3.4 / 4.4)

### Goal
Eliminate memory spikes and reduce time-to-first-byte (TTFB) when fetching large message lists. Instead of building the entire JSON response in memory, stream it to the client.

### Implementation Details
- **Endpoint**: `GET /sessions/{id}/messages/stream`
- **Format**: Newline Delimited JSON (NDJSON) or chunked JSON array.
- **Mechanism**:
    1.  Execute DuckDB query to get a cursor.
    2.  Use FastAPI `StreamingResponse`.
    3.  Iterate over the cursor, serializing one row at a time and yielding it immediately.

### Tasks
- [ ] Implement NDJSON generator in `routers/sessions.py`.
- [ ] Update frontend to handle streaming responses (consume chunks as they arrive).
- [ ] Add "Export to JSON" feature using the streaming endpoint.

---

## 2. Parquet Conversion (Priority 5.1)

### Goal
Drastically improve analytics performance for historical data. JSONL parsing is CPU-intensive; Parquet is columnar and binary, allowing DuckDB to read only necessary columns (e.g., just `usage` for token counting) without parsing message content.

### Implementation Details
- **Trigger**: When a session is detected as "completed" (no writes for >1 hour) or explicitly archived.
- **Action**: Convert `session-id.jsonl` -> `session-id.parquet`.
- **Integration**: Update `get_session_view_query` to prefer `.parquet` file if it exists.

### Tasks
- [ ] Create `services/archiver.py` to handle conversion.
- [ ] Add background task to scan for convertible sessions.
- [ ] Update database service to transparently read from Parquet or JSONL.

---

## 3. Persistent DuckDB & Materialized Views (Priority 5.2)

### Goal
Move from in-memory views (which are lost on restart) to a persistent file-backed database (`~/.claude/tracer.duckdb`). This allows us to maintain materialized views of expensive aggregations.

### Implementation Details
- **Storage**: Single `.duckdb` file instead of `:memory:`.
- **Schema**:
    - `projects` table (synced from filesystem).
    - `sessions` table (synced from filesystem).
    - `messages` view (unioned over all session files).
- **Benefit**: Zero-latency startup for previously indexed data.

### Tasks
- [ ] Change `DuckDBPool` to connect to a file path.
- [ ] Implement schema migration logic.
- [ ] Create materialized views for project metrics.

---

## 4. File Change Watcher (Priority 5.3)

### Goal
Replace polling and mtime checks with real-time file system events. This allows the UI to update immediately when Claude Code writes a new log entry.

### Implementation Details
- **Library**: `watchdog` (Python).
- **Mechanism**:
    1.  Watch `~/.claude/projects/` recursively.
    2.  On `FileModified` event:
        - Invalidate specific caches immediately.
        - Push update to frontend via WebSocket (optional future step) or SSE.
        - Trigger incremental indexing.

### Tasks
- [ ] Implement `ProjectWatcher` service.
- [ ] Integrate with `GlobalIndex` to update in real-time.
- [ ] Integrate with `PersistentCache` to invalidate entries.

---

## 5. Query Pre-filtering (Priority 3.3)

### Goal
Optimize the "Comprehensive Message Query" by pushing filters down into the sub-queries before the `UNION ALL`.

### Implementation Details
- **Current**: `(SELECT * FROM A UNION SELECT * FROM B) WHERE type='user'`
- **Optimized**: `(SELECT * FROM A WHERE type='user') UNION (SELECT * FROM B WHERE type='user')`
- **Benefit**: DuckDB can skip reading entire JSON structures for message types that are filtered out.

### Tasks
- [ ] Refactor `MESSAGES_COMPREHENSIVE_QUERY_V2` to accept injected filter clauses.
- [ ] Dynamically build the query based on request parameters.

---

## 6. Worker Process Pool (Priority 5.4)

### Goal
Offload heavy CPU tasks (like Parquet conversion or deep analytics across all projects) to a separate process to keep the API responsive.

### Implementation Details
- **Tools**: `concurrent.futures.ProcessPoolExecutor` or a task queue like `Celery`/`RQ`.
- **Use Cases**:
    - converting 100+ JSONL files to Parquet.
    - Re-indexing the entire history.
    - Exporting large datasets.

### Tasks
- [ ] Setup `ProcessPoolExecutor` in `services/workers.py`.
- [ ] Define isolated task functions (must be picklable).
- [ ] Create API endpoints to trigger and monitor background tasks.

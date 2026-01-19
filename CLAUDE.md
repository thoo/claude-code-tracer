# Claude Code Tracer

Analytics dashboard for visualizing Claude Code session traces. Reads session logs from `~/.claude/projects/` and provides insights into token usage, costs, tool usage patterns, and code changes.

## Quick Reference

### Using Makefile (Recommended)

```bash
make install          # Install all dependencies
make dev              # Run frontend + backend dev servers
make build            # Build frontend and bundle into package
make run              # Run the bundled app
make test             # Run tests
make check            # Run lint + test
```

### Manual Commands

```bash
# Backend (port 8420)
cd backend && uv run uvicorn claude_code_tracer.main:app --reload --port 8420

# Frontend (proxies to :8420)
cd frontend && npm run dev

# Tests & Quality
cd backend && uv run pytest
cd backend && uv run ruff check src/ && uv run mypy src/
```

### CLI Usage (after `make build` or `pip install`)

```bash
cctracer              # Start server, opens browser
cctracer --port 9000  # Custom port
cctracer --no-browser # Don't auto-open browser

# Long form also works
claude-code-tracer
```

## Project Structure

```
backend/src/claude_code_tracer/
├── main.py              # FastAPI app, lifespan, CORS, static file serving
├── cli.py               # CLI entry point (claude-code-tracer command)
├── static/              # Bundled frontend assets (populated by make build)
├── routers/             # API endpoints (sessions, metrics, subagents)
├── models/              # Pydantic models (entries, responses)
├── services/
│   ├── database.py      # DuckDB pool, session views, file discovery
│   ├── log_parser.py    # JSONL parsing, aggregation logic
│   ├── queries.py       # SQL query templates
│   ├── metrics.py       # Cost calculation, pricing lookup
│   ├── cache.py         # File-mtime and persistent caching
│   ├── index.py         # Background index service
│   └── async_io.py      # Async wrappers for blocking operations
└── utils/datetime.py    # UTC-aware datetime utilities

frontend/src/
├── pages/               # Overview, ProjectDashboard, SessionDetail, SubagentDetail
├── components/          # Common UI, charts, modals
├── hooks/useApi.ts      # React Query hooks
├── lib/api.ts           # API client
└── context/             # Theme context
```

## Key Technologies

- **Backend**: FastAPI, DuckDB, Pydantic, orjson, loguru
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, React Query, Recharts
- **Quality**: ruff, mypy (strict), pytest, pre-commit hooks

## Known Issues & Reminders

### Datetime Timezone Handling

When sorting or comparing datetime objects, always normalize timezones to avoid `TypeError: can't compare offset-naive and offset-aware datetimes`.

Use this pattern:
```python
from datetime import UTC, datetime

def normalize_datetime(dt: datetime | None) -> datetime:
    if dt is None:
        return datetime.min.replace(tzinfo=UTC)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
```

This is especially important when:
- Sorting sessions by `start_time`
- Comparing timestamps from different sources (index files vs JSONL parsing)

### DuckDB Type Handling from JSON Sources

When querying JSONL files with DuckDB's `read_json_auto()`, timestamps and UUIDs are returned as **strings**, not native Python types.

**Timestamp Issue:**
```python
# DuckDB returns: '2026-01-18T18:08:29.530Z' (str)
# NOT: datetime(2026, 1, 18, 18, 8, 29, ...) (datetime)

# BAD - will fail with "'str' object has no attribute 'isoformat'"
def encode_cursor(timestamp: datetime, uuid: str) -> str:
    ts_str = timestamp.isoformat()  # Assumes datetime object

# GOOD - handle both types
def encode_cursor(timestamp: datetime | str, uuid: str) -> str:
    if isinstance(timestamp, str):
        ts_str = timestamp  # Already ISO string from DuckDB
    else:
        ts_str = timestamp.isoformat()
```

**UUID Type Issue:**
```python
# DuckDB stores uuid column as UUID type, but cursor values are strings
# BAD - type mismatch error
WHERE (timestamp, uuid) > ('{ts}', '{uuid_str}')

# GOOD - cast uuid to VARCHAR for comparison
WHERE (timestamp, CAST(uuid AS VARCHAR)) > ('{ts}', '{uuid_str}')
```

**Timestamp Column Type Variance:**
```sql
-- timestamp column may be VARCHAR (from JSONL) or TIMESTAMP (from tests/views)
-- String formats also differ: ISO uses 'T', DuckDB TIMESTAMP uses space
-- ISO:    '2024-01-01T12:00:00'
-- DuckDB: '2024-01-01 12:00:00'

-- BAD - type mismatch if column is VARCHAR but comparing to TIMESTAMP
WHERE timestamp > TIMESTAMP '{cursor_ts}'

-- BAD - lexicographic comparison fails due to 'T' vs space
WHERE CAST(timestamp AS VARCHAR) > '{cursor_ts}'

-- GOOD - cast both sides to TIMESTAMP for consistent comparison
WHERE CAST(timestamp AS TIMESTAMP) > TIMESTAMP '{cursor_ts}'
```

This is especially important when:
- Building cursor-based pagination with timestamp/uuid pairs
- Extracting values from DuckDB query results for further processing
- Comparing query results with string literals in WHERE clauses
- Writing queries that work with both test fixtures and real JSONL data

## API Endpoints

| Route | Description |
|-------|-------------|
| `GET /api/projects` | List all projects with stats |
| `GET /api/projects/{hash}/sessions` | Sessions for a project |
| `GET /api/sessions/{hash}/{id}/messages` | Paginated messages (supports filters) |
| `GET /api/sessions/{hash}/{id}/metrics` | Session metrics (tokens, cost) |
| `GET /api/sessions/{hash}/{id}/tools` | Tool usage breakdown |
| `GET /api/subagents/{hash}/{session}/{agent}` | Subagent details |
| `GET /api/metrics/daily/{hash}` | Daily metrics for project |

## Data Flow

```
~/.claude/projects/{hash}/
├── {sessionid}.jsonl      # Session messages (read by DuckDB)
├── sessions-index.json    # Project metadata
└── subagents/
    └── agent-{id}.jsonl   # Subagent logs
```

## Caching Strategy

- **Session Views**: DuckDB temporary views (TTL: 5 min) to avoid repeated `read_json_auto()`
- **File-Mtime Cache**: In-memory cache invalidated when session file changes
- **Persistent Cache**: `~/.claude/tracer-cache.json` for aggregate metrics across restarts

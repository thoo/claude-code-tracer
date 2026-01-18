# Claude Code Tracer

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

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

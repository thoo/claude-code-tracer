"""Datetime standardization utilities.

This module provides consistent UTC-aware datetime handling across the application.
It eliminates TypeError: can't compare offset-naive and offset-aware datetimes.

Priority 4.5 implementation.
"""

from datetime import UTC, datetime


def normalize_datetime(dt: datetime | str | None) -> datetime:
    """Always return a timezone-aware (UTC) datetime.

    This function ensures consistent datetime handling across the application:
    - None -> datetime.min in UTC (safe for sorting/comparison)
    - ISO string -> parsed datetime in UTC
    - Naive datetime -> assumed UTC, made aware
    - Aware datetime -> converted to UTC

    Args:
        dt: A datetime object, ISO format string, or None

    Returns:
        A timezone-aware datetime in UTC

    Examples:
        >>> normalize_datetime(None)
        datetime.datetime(1, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)

        >>> normalize_datetime("2024-01-15T10:30:00Z")
        datetime.datetime(2024, 1, 15, 10, 30, tzinfo=datetime.timezone.utc)

        >>> from datetime import datetime
        >>> normalize_datetime(datetime(2024, 1, 15, 10, 30))
        datetime.datetime(2024, 1, 15, 10, 30, tzinfo=datetime.timezone.utc)
    """
    if dt is None:
        return datetime.min.replace(tzinfo=UTC)

    if isinstance(dt, str):
        try:
            # Handle ISO format with 'Z' suffix (common in JSON)
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=UTC)

    if dt.tzinfo is None:
        # Naive datetime - assume UTC
        return dt.replace(tzinfo=UTC)

    # Already aware - convert to UTC
    return dt.astimezone(UTC)


def parse_timestamp(value: str | datetime | None) -> datetime | None:
    """Parse a timestamp value that may be a string or datetime.

    Unlike normalize_datetime, this returns None for invalid/missing values
    instead of datetime.min. Use this when you need to distinguish between
    "no timestamp" and "earliest possible timestamp".

    Args:
        value: A datetime object, ISO format string, or None

    Returns:
        A timezone-aware datetime in UTC, or None if parsing fails
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(UTC)
    except (ValueError, AttributeError):
        return None


def now_utc() -> datetime:
    """Get current time as timezone-aware UTC datetime.

    Use this instead of datetime.now() or datetime.utcnow() throughout
    the application to ensure consistent timezone handling.
    """
    return datetime.now(UTC)

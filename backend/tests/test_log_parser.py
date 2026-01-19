from datetime import UTC, datetime

from claude_code_tracer.services.log_parser import _parse_timestamp, _parse_token_usage


def test_parse_timestamp():
    # ISO format with Z
    ts = _parse_timestamp("2024-01-01T12:00:00Z")
    assert ts == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    # ISO format with offset
    ts = _parse_timestamp("2024-01-01T12:00:00+00:00")
    assert ts == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    # Datetime object (naive) - now normalized to UTC per Priority 4.5
    dt = datetime(2024, 1, 1, 12, 0, 0)
    result = _parse_timestamp(dt)
    assert result == datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    # Datetime object (aware)
    dt_aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert _parse_timestamp(dt_aware) == dt_aware

    # None
    assert _parse_timestamp(None) is None

    # Invalid string
    assert _parse_timestamp("not-a-date") is None


def test_parse_token_usage():
    # Normal result
    result = (100, 50, 20, 10)
    usage = _parse_token_usage(result)
    assert usage.input_tokens == 100
    assert usage.output_tokens == 50
    assert usage.cache_creation_input_tokens == 20
    assert usage.cache_read_input_tokens == 10

    # None result
    usage = _parse_token_usage(None)
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0

    # Empty result (though unlikely from fetchone)
    usage = _parse_token_usage(())
    assert usage.input_tokens == 0


def test_parse_session_summary(sample_session_file):
    project_hash, session_id, session_path = sample_session_file
    from claude_code_tracer.services.log_parser import parse_session_summary

    summary = parse_session_summary(project_hash, session_id)

    assert summary is not None
    assert summary.session_id == session_id
    assert summary.tokens.input_tokens == 10
    assert summary.tokens.output_tokens == 20
    assert summary.tokens.cache_creation_input_tokens == 5
    assert summary.tokens.cache_read_input_tokens == 2
    assert summary.message_count >= 1  # Depending on how MESSAGE_COUNT_QUERY is defined
    assert summary.tool_calls == 1


def test_session_summary_caching(sample_session_file):
    import os
    import time

    from claude_code_tracer.services.log_parser import (
        _cached_session_summary_impl,
        parse_session_summary,
    )

    project_hash, session_id, session_path = sample_session_file

    # clear cache before test
    _cached_session_summary_impl.cache_clear()

    # 1. First Call - Should be a Miss
    summary1 = parse_session_summary(project_hash, session_id)
    assert summary1 is not None
    info = _cached_session_summary_impl.cache_info()
    assert info.hits == 0
    assert info.misses == 1

    # 2. Second Call - Should be a Hit
    summary2 = parse_session_summary(project_hash, session_id)
    assert summary2 is not None
    info = _cached_session_summary_impl.cache_info()
    assert info.hits == 1
    assert info.misses == 1

    # 3. Modify File (Change mtime) - Should cause a Miss (re-parse)
    # Ensure mtime actually changes (filesystem granularity can be coarse)
    old_mtime = session_path.stat().st_mtime
    time.sleep(0.01)  # Small sleep to ensure different mtime if fast filesystem
    os.utime(session_path, None)  # Touch file
    new_mtime = session_path.stat().st_mtime

    if new_mtime == old_mtime:
        # Fallback for fast filesystems or low resolution timestamps: force a manual offset
        os.utime(session_path, (new_mtime + 1, new_mtime + 1))

    parse_session_summary(project_hash, session_id)
    info = _cached_session_summary_impl.cache_info()
    assert info.hits == 1
    assert info.misses == 2


def test_session_summary_cache_identity(sample_session_file):
    from claude_code_tracer.services.log_parser import (
        _cached_session_summary_impl,
        parse_session_summary,
    )

    project_hash, session_id, _ = sample_session_file

    # Clear cache to start fresh
    _cached_session_summary_impl.cache_clear()

    # 1. Get summary
    s1 = parse_session_summary(project_hash, session_id)

    # 2. Get it again
    s2 = parse_session_summary(project_hash, session_id)

    # 3. Verify it is the EXACT same object in memory
    assert s1 is s2

    # 4. Prove that modifying s1 affects s2 (demonstrating why we need model_copy() in the router)
    original_status = s1.status
    s1.status = "corrupted"
    assert s2.status == "corrupted"

    # Reset for other tests/cleanup
    s1.status = original_status

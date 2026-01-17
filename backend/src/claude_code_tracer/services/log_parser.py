"""JSONL log file parsing service using DuckDB."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from duckdb import DuckDBPyConnection

from ..models.entries import TokenUsage
from ..models.responses import (
    CodeChangesResponse,
    CostBreakdown,
    ErrorEntry,
    ErrorsResponse,
    FileChange,
    SessionMetricsResponse,
    SessionSummary,
    SkillsResponse,
    SkillUsage,
    SubagentListResponse,
    SubagentResponse,
    ToolUsageResponse,
    ToolUsageStats,
)
from .database import get_connection, get_session_path, get_subagent_files_for_session, list_sessions
from .metrics import calculate_cache_hit_rate, calculate_cost, count_lines_changed
from .queries import (
    CODE_CHANGES_QUERY,
    ERROR_COUNT_QUERY,
    MESSAGE_COUNT_QUERY,
    SESSION_STATUS_QUERY,
    SESSION_TIMERANGE_QUERY,
    SKILL_CALLS_QUERY,
    SUBAGENT_CALLS_QUERY,
    TOKEN_USAGE_BY_MODEL_QUERY,
    TOKEN_USAGE_QUERY,
    TOOL_USAGE_QUERY,
)


def _parse_timestamp(value: str | datetime | None) -> datetime | None:
    """Parse a timestamp value that may be a string or datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _parse_token_usage_from_row(row: tuple) -> TokenUsage:
    """Parse token usage from a model query result row.

    Expected row format: (model, input_tokens, output_tokens, cache_creation, cache_read)
    """
    return TokenUsage(
        input_tokens=row[1] or 0,
        output_tokens=row[2] or 0,
        cache_creation_input_tokens=row[3] or 0,
        cache_read_input_tokens=row[4] or 0,
    )


def _execute_query(conn: DuckDBPyConnection, query: str, default: Any = None) -> Any:
    """Execute a query and return result, or default on error."""
    try:
        return conn.execute(query).fetchone()
    except Exception:
        return default


def _execute_query_all(conn: DuckDBPyConnection, query: str) -> list:
    """Execute a query and return all results, or empty list on error."""
    try:
        return conn.execute(query).fetchall()
    except Exception:
        return []


def _parse_token_usage(result: tuple | None) -> TokenUsage:
    """Parse token usage from query result."""
    if not result:
        return TokenUsage()
    return TokenUsage(
        input_tokens=result[0] or 0,
        output_tokens=result[1] or 0,
        cache_creation_input_tokens=result[2] or 0,
        cache_read_input_tokens=result[3] or 0,
    )


def _get_error_count(conn: DuckDBPyConnection, path: Path) -> int:
    """Get error count from a session file."""
    result = _execute_query(conn, ERROR_COUNT_QUERY.format(path=str(path)), (0,))
    return result[0] if result else 0


def _accumulate_subagent_data(
    conn: DuckDBPyConnection,
    subagent_files: list[Path],
    tokens: TokenUsage,
    cost_accumulator: CostBreakdown | None = None,
    models_used: list[str] | None = None,
) -> float:
    """Accumulate token usage and costs from subagent files.

    Modifies tokens in place. If cost_accumulator is provided, accumulates detailed costs.
    If models_used is provided, appends unique models.

    Returns: Total cost from all subagents.
    """
    total_cost = 0.0

    for subagent_path in subagent_files:
        model_rows = _execute_query_all(
            conn, TOKEN_USAGE_BY_MODEL_QUERY.format(path=str(subagent_path))
        )
        for row in model_rows:
            model = row[0]
            if not model:
                continue

            sub_tokens = _parse_token_usage_from_row(row)

            tokens.input_tokens += sub_tokens.input_tokens
            tokens.output_tokens += sub_tokens.output_tokens
            tokens.cache_creation_input_tokens += sub_tokens.cache_creation_input_tokens
            tokens.cache_read_input_tokens += sub_tokens.cache_read_input_tokens

            sub_cost = calculate_cost(sub_tokens, model)
            total_cost += sub_cost.total_cost

            if cost_accumulator is not None:
                cost_accumulator.input_cost += sub_cost.input_cost
                cost_accumulator.output_cost += sub_cost.output_cost
                cost_accumulator.cache_creation_cost += sub_cost.cache_creation_cost
                cost_accumulator.cache_read_cost += sub_cost.cache_read_cost

            if models_used is not None and model not in models_used:
                models_used.append(model)

    return total_cost


def _count_subagent_errors(conn: DuckDBPyConnection, subagent_files: list[Path]) -> int:
    """Count errors across all subagent files."""
    return sum(_get_error_count(conn, path) for path in subagent_files)


def _determine_session_status(conn: DuckDBPyConnection, path_str: str, session_path: Path) -> str:
    """Determine session status based on file state and content."""
    status_result = _execute_query(conn, SESSION_STATUS_QUERY.format(path=path_str))

    file_mtime = datetime.fromtimestamp(session_path.stat().st_mtime, tz=timezone.utc)
    seconds_since_modified = (datetime.now(timezone.utc) - file_mtime).total_seconds()

    if status_result:
        has_summary, last_content = status_result[0], status_result[1]

        if has_summary:
            return "completed"
        if last_content and "interrupted" in str(last_content).lower():
            return "interrupted"
        if seconds_since_modified < 60:
            return "running"
        if seconds_since_modified < 300:
            return "idle"

    if seconds_since_modified < 60:
        return "running"

    return "unknown"


def parse_session_summary(project_hash: str, session_id: str) -> SessionSummary | None:
    """Parse a session JSONL file and return summary statistics."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return None

    with get_connection() as conn:
        path_str = str(session_path)

        token_result = _execute_query(conn, TOKEN_USAGE_QUERY.format(path=path_str))
        tokens = _parse_token_usage(token_result)

        count_result = _execute_query(conn, MESSAGE_COUNT_QUERY.format(path=path_str), (0, 0, 0))
        message_count = count_result[0] if count_result else 0

        tool_result = _execute_query_all(conn, TOOL_USAGE_QUERY.format(path=path_str))
        tool_calls = sum(row[1] for row in tool_result)

        time_result = _execute_query(conn, SESSION_TIMERANGE_QUERY.format(path=path_str))
        start_time = (
            _parse_timestamp(time_result[0]) if time_result and time_result[0] else datetime.now()
        )
        end_time = _parse_timestamp(time_result[1]) if time_result and time_result[1] else None

        duration_seconds = 0
        if start_time and end_time:
            duration_seconds = int((end_time - start_time).total_seconds())

        # Calculate cost per model for accurate total
        model_tokens_result = _execute_query_all(
            conn, TOKEN_USAGE_BY_MODEL_QUERY.format(path=path_str)
        )
        total_cost = 0.0
        for row in model_tokens_result:
            model = row[0]
            if model:
                model_cost = calculate_cost(_parse_token_usage_from_row(row), model)
                total_cost += model_cost.total_cost

        # Include subagent token usage and costs
        subagent_files = get_subagent_files_for_session(project_hash, session_id)
        total_cost += _accumulate_subagent_data(conn, subagent_files, tokens)

        # Count errors from main session and subagents
        error_count = _get_error_count(conn, session_path)
        error_count += _count_subagent_errors(conn, subagent_files)

        status = _determine_session_status(conn, path_str, session_path)

        return SessionSummary(
            session_id=session_id,
            status=status,
            start_time=start_time,
            end_time=end_time,
            duration_seconds=duration_seconds,
            message_count=message_count,
            tool_calls=tool_calls,
            tokens=tokens,
            cost=total_cost,
            errors=error_count,
        )


def get_session_tool_usage(project_hash: str, session_id: str) -> ToolUsageResponse:
    """Get tool usage statistics for a session."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return ToolUsageResponse()

    with get_connection() as conn:
        result = _execute_query_all(conn, TOOL_USAGE_QUERY.format(path=str(session_path)))
        tools = [
            ToolUsageStats(
                name=row[0],
                count=row[1],
                avg_duration_seconds=row[2] or 0.0,
                error_count=row[3] or 0,
            )
            for row in result
            if row[0]
        ]
        return ToolUsageResponse(tools=tools, total_calls=sum(t.count for t in tools))


def get_session_metrics(project_hash: str, session_id: str) -> SessionMetricsResponse:
    """Get detailed metrics for a session."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return SessionMetricsResponse()

    with get_connection() as conn:
        path_str = str(session_path)

        token_result = _execute_query(conn, TOKEN_USAGE_QUERY.format(path=path_str))
        if not token_result:
            return SessionMetricsResponse()
        tokens = _parse_token_usage(token_result)

        model_tokens_result = _execute_query_all(
            conn, TOKEN_USAGE_BY_MODEL_QUERY.format(path=path_str)
        )

        count_result = _execute_query(conn, MESSAGE_COUNT_QUERY.format(path=path_str), (0, 0, 0))
        message_count = count_result[0] if count_result else 0

        tool_result = _execute_query_all(conn, TOOL_USAGE_QUERY.format(path=path_str))
        tool_calls = sum(row[1] for row in tool_result)

        time_result = _execute_query(conn, SESSION_TIMERANGE_QUERY.format(path=path_str))
        duration_seconds = 0
        if time_result and time_result[0] and time_result[1]:
            start_ts = _parse_timestamp(time_result[0])
            end_ts = _parse_timestamp(time_result[1])
            if start_ts and end_ts:
                duration_seconds = int((end_ts - start_ts).total_seconds())

        # Calculate cost per model and sum up
        models_used: list[str] = []
        total_cost = CostBreakdown()
        for row in model_tokens_result:
            model = row[0]
            if model:
                models_used.append(model)
                model_cost = calculate_cost(_parse_token_usage_from_row(row), model)
                total_cost.input_cost += model_cost.input_cost
                total_cost.output_cost += model_cost.output_cost
                total_cost.cache_creation_cost += model_cost.cache_creation_cost
                total_cost.cache_read_cost += model_cost.cache_read_cost

        # Include subagent token usage and costs
        subagent_files = get_subagent_files_for_session(project_hash, session_id)
        _accumulate_subagent_data(conn, subagent_files, tokens, total_cost, models_used)

        cache_hit_rate = calculate_cache_hit_rate(
            tokens.cache_read_input_tokens,
            tokens.cache_creation_input_tokens,
            tokens.input_tokens,
        )

        # Count errors from main session and subagents
        error_count = _get_error_count(conn, session_path)
        error_count += _count_subagent_errors(conn, subagent_files)

        return SessionMetricsResponse(
            tokens=tokens,
            cost=total_cost,
            duration_seconds=duration_seconds,
            message_count=message_count,
            tool_calls=tool_calls,
            error_count=error_count,
            models_used=models_used,
            cache_hit_rate=cache_hit_rate,
        )


def get_session_subagents(project_hash: str, session_id: str) -> SubagentListResponse:
    """Get subagents spawned in a session."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return SubagentListResponse()

    with get_connection() as conn:
        result = _execute_query_all(conn, SUBAGENT_CALLS_QUERY.format(path=str(session_path)))
        subagents = [
            SubagentResponse(
                agent_id=row[0],
                subagent_type=row[1] or "unknown",
                description=row[2],
                start_time=row[4] if len(row) > 4 else None,
            )
            for row in result
            if row[0]
        ]
        return SubagentListResponse(subagents=subagents, total_count=len(subagents))


def get_session_skills(project_hash: str, session_id: str) -> SkillsResponse:
    """Get skills invoked in a session."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return SkillsResponse()

    with get_connection() as conn:
        result = _execute_query_all(conn, SKILL_CALLS_QUERY.format(path=str(session_path)))

        skill_counts: dict[str, dict[str, Any]] = {}
        for row in result:
            skill_name = row[1]
            if not skill_name:
                continue
            timestamp = row[3] if len(row) > 3 else None
            if skill_name not in skill_counts:
                skill_counts[skill_name] = {"count": 0, "last_used": None}
            skill_counts[skill_name]["count"] += 1
            if timestamp:
                skill_counts[skill_name]["last_used"] = timestamp

        skills = [
            SkillUsage(
                skill_name=name,
                invocation_count=data["count"],
                last_used=data["last_used"],
            )
            for name, data in skill_counts.items()
        ]

        return SkillsResponse(
            skills=skills, total_invocations=sum(s.invocation_count for s in skills)
        )


def get_session_code_changes(project_hash: str, session_id: str) -> CodeChangesResponse:
    """Get code changes made in a session."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return CodeChangesResponse()

    with get_connection() as conn:
        result = _execute_query_all(conn, CODE_CHANGES_QUERY.format(path=str(session_path)))

        files_created = 0
        files_modified = 0
        total_lines_added = 0
        total_lines_removed = 0
        changes_by_file: list[FileChange] = []

        for row in result:
            file_path, old_string, new_string, write_content, operation = row

            if operation == "Write":
                files_created += 1
                lines_added = write_content.count("\n") + 1 if write_content else 0
                lines_removed = 0
            else:
                files_modified += 1
                lines_added, lines_removed = count_lines_changed(old_string, new_string)

            total_lines_added += lines_added
            total_lines_removed += lines_removed

            if file_path:
                changes_by_file.append(
                    FileChange(
                        file_path=file_path,
                        operation=operation,
                        lines_added=lines_added,
                        lines_removed=lines_removed,
                    )
                )

        return CodeChangesResponse(
            files_created=files_created,
            files_modified=files_modified,
            lines_added=total_lines_added,
            lines_removed=total_lines_removed,
            net_lines=total_lines_added - total_lines_removed,
            changes_by_file=changes_by_file,
        )


def get_session_errors(project_hash: str, session_id: str) -> ErrorsResponse:
    """Get errors from a session."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return ErrorsResponse()

    errors = _parse_errors_from_file(session_path)
    return ErrorsResponse(errors=errors, total=len(errors))


def _parse_errors_from_file(session_path: Path) -> list[ErrorEntry]:
    """Parse error entries from a session file."""
    errors: list[ErrorEntry] = []

    try:
        with open(session_path) as f:
            for line in f:
                error = _parse_error_from_line(line)
                if error:
                    errors.append(error)
    except Exception:
        pass

    return errors


def _parse_error_from_line(line: str) -> ErrorEntry | None:
    """Parse a single error entry from a JSONL line."""
    try:
        entry = json.loads(line)
        if entry.get("type") != "user":
            return None

        content = entry.get("message", {}).get("content")
        if not isinstance(content, list):
            return None

        for item in content:
            if isinstance(item, dict) and item.get("is_error"):
                error_content = item.get("content", "")
                if isinstance(error_content, list):
                    error_content = " ".join(str(c.get("text", c)) for c in error_content)

                parsed_ts = _parse_timestamp(entry.get("timestamp", ""))
                return ErrorEntry(
                    timestamp=parsed_ts or datetime.now(),
                    tool_name=None,
                    error_message=str(error_content)[:500],
                    uuid=entry.get("uuid", ""),
                )
    except (json.JSONDecodeError, KeyError, ValueError):
        pass

    return None


def _normalize_timezone(dt: datetime | None) -> datetime | None:
    """Ensure datetime has UTC timezone for comparison."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_project_total_metrics(
    project_hash: str, session_ids: list[str] | None = None
) -> dict[str, Any]:
    """Get aggregated metrics for a project."""
    from .database import get_project_dir

    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return {}

    if session_ids is None:
        sessions = list_sessions(project_hash)
        session_ids = [s["session_id"] for s in sessions]

    input_tokens = 0
    output_tokens = 0
    cache_creation = 0
    cache_read = 0
    total_cost = 0.0
    first_activity: datetime | None = None
    last_activity: datetime | None = None

    for session_id in session_ids:
        summary = parse_session_summary(project_hash, session_id)
        if not summary:
            continue

        input_tokens += summary.tokens.input_tokens
        output_tokens += summary.tokens.output_tokens
        cache_creation += summary.tokens.cache_creation_input_tokens
        cache_read += summary.tokens.cache_read_input_tokens
        total_cost += summary.cost

        start = _normalize_timezone(summary.start_time)
        if start and (first_activity is None or start < first_activity):
            first_activity = start

        end = _normalize_timezone(summary.end_time)
        if end and (last_activity is None or end > last_activity):
            last_activity = end

    return {
        "tokens": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
        },
        "total_cost": total_cost,
        "first_activity": first_activity,
        "last_activity": last_activity,
        "session_count": len(session_ids),
    }

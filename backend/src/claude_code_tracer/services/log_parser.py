"""JSONL log file parsing service using DuckDB."""

import json
from datetime import UTC, datetime
from functools import lru_cache
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
from ..utils.datetime import now_utc, parse_timestamp
from .database import (
    get_connection,
    get_session_path,
    get_session_view_query,
    get_subagent_files_for_session,
    get_subagent_path_for_session,
    list_sessions,
)
from .metrics import calculate_cache_hit_rate, calculate_cost, count_lines_changed
from .queries import (
    AGGREGATE_ALL_PROJECTS_QUERY,
    AGGREGATE_PROJECT_SESSIONS_QUERY,
    CODE_CHANGES_QUERY_V2,
    ERROR_COUNT_GLOB_QUERY,
    ERROR_COUNT_QUERY_V2,
    MESSAGE_COUNT_QUERY_V2,
    SESSION_STATUS_QUERY_V2,
    SESSION_TIMERANGE_QUERY_V2,
    SKILL_CALLS_QUERY_V2,
    SUBAGENT_CALLS_WITH_AGENT_ID_QUERY_V2,
    TOKEN_USAGE_BY_MODEL_GLOB_QUERY,
    TOKEN_USAGE_BY_MODEL_QUERY_V2,
    TOKEN_USAGE_QUERY_V2,
    TOOL_USAGE_QUERY_V2,
)

# Use standardized datetime utility (Priority 4.5)
_parse_timestamp = parse_timestamp


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


def _get_error_count(conn: DuckDBPyConnection, path: Path, source: str | None = None) -> int:
    """Get error count from a session file.

    Args:
        conn: DuckDB connection
        path: Path to session file
        source: Optional pre-computed source query string. If not provided, will be computed.
    """
    if source is None:
        source = get_session_view_query(path)
    result = _execute_query(conn, ERROR_COUNT_QUERY_V2.format(source=source), (0,))
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

    Uses session views for each subagent file to reduce I/O.

    Returns: Total cost from all subagents.
    """
    total_cost = 0.0

    for subagent_path in subagent_files:
        # Use session view for each subagent file
        source = get_session_view_query(subagent_path)
        model_rows = _execute_query_all(conn, TOKEN_USAGE_BY_MODEL_QUERY_V2.format(source=source))
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


def _determine_session_status(
    conn: DuckDBPyConnection, session_path: Path, source: str | None = None
) -> str:
    """Determine session status based on file state and content.

    Args:
        conn: DuckDB connection
        session_path: Path to session file
        source: Optional pre-computed source query string. If not provided, will be computed.
    """
    file_mtime = datetime.fromtimestamp(session_path.stat().st_mtime, tz=UTC)
    seconds_since_modified = (now_utc() - file_mtime).total_seconds()

    if source is None:
        source = get_session_view_query(session_path)
    status_result = _execute_query(conn, SESSION_STATUS_QUERY_V2.format(source=source))
    if not status_result:
        return "running" if seconds_since_modified < 60 else "unknown"

    has_summary, last_content = status_result[0], status_result[1]

    if has_summary:
        return "completed"
    if last_content and "interrupted" in str(last_content).lower():
        return "interrupted"
    if seconds_since_modified < 60:
        return "running"
    if seconds_since_modified < 300:
        return "idle"
    return "unknown"


@lru_cache(maxsize=500)
def _cached_session_summary_impl(
    path_str: str, mtime: float, project_hash: str, session_id: str
) -> SessionSummary:
    """Cached implementation of session summary parsing.

    Uses session views to avoid re-parsing the JSONL file for each query (Priority 2.3).
    All queries share the same session view, significantly reducing I/O.
    """
    session_path = Path(path_str)

    with get_connection() as conn:
        # Create/reuse session view for all queries (Priority 2.3 optimization)
        source = get_session_view_query(session_path)

        token_result = _execute_query(conn, TOKEN_USAGE_QUERY_V2.format(source=source))
        tokens = _parse_token_usage(token_result)

        count_result = _execute_query(conn, MESSAGE_COUNT_QUERY_V2.format(source=source), (0, 0, 0))
        message_count = count_result[0] if count_result else 0

        tool_result = _execute_query_all(conn, TOOL_USAGE_QUERY_V2.format(source=source))
        tool_calls = sum(row[1] for row in tool_result)

        time_result = _execute_query(conn, SESSION_TIMERANGE_QUERY_V2.format(source=source))
        start_time = (
            _parse_timestamp(time_result[0]) if time_result and time_result[0] else None
        ) or datetime.now()
        end_time = _parse_timestamp(time_result[1]) if time_result and time_result[1] else None

        duration_seconds = 0
        if start_time and end_time:
            duration_seconds = int((end_time - start_time).total_seconds())

        # Calculate cost per model for accurate total
        model_tokens_result = _execute_query_all(
            conn, TOKEN_USAGE_BY_MODEL_QUERY_V2.format(source=source)
        )
        total_cost = 0.0
        for row in model_tokens_result:
            model = row[0]
            if model:
                model_cost = calculate_cost(_parse_token_usage_from_row(row), model)
                total_cost += model_cost.total_cost

        # Include subagent token usage and costs using batch query (Priority 2.4)
        subagent_files = get_subagent_files_for_session(project_hash, session_id)
        if subagent_files:
            sub_tokens, sub_cost, _ = get_batch_subagent_metrics(subagent_files)
            tokens.input_tokens += sub_tokens.input_tokens
            tokens.output_tokens += sub_tokens.output_tokens
            tokens.cache_creation_input_tokens += sub_tokens.cache_creation_input_tokens
            tokens.cache_read_input_tokens += sub_tokens.cache_read_input_tokens
            total_cost += sub_cost

        # Count errors from main session and subagents using batch query
        # Reuse source for main session error count
        error_count = _get_error_count(conn, session_path, source)
        if subagent_files:
            error_count += get_batch_error_count(subagent_files)

        # Reuse source for status determination
        status = _determine_session_status(conn, session_path, source)

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
            subagent_count=len(subagent_files),
        )


def parse_session_summary(project_hash: str, session_id: str) -> SessionSummary | None:
    """Parse a session JSONL file and return summary statistics."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return None

    mtime = session_path.stat().st_mtime
    return _cached_session_summary_impl(str(session_path), mtime, project_hash, session_id)


def get_session_tool_usage(project_hash: str, session_id: str) -> ToolUsageResponse:
    """Get tool usage statistics for a session.

    Uses session views for reduced I/O (Priority 2.3).
    """
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return ToolUsageResponse()

    with get_connection() as conn:
        source = get_session_view_query(session_path)
        result = _execute_query_all(conn, TOOL_USAGE_QUERY_V2.format(source=source))
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
    """Get detailed metrics for a session.

    Uses session views for reduced I/O (Priority 2.3).
    """
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return SessionMetricsResponse()

    with get_connection() as conn:
        # Create/reuse session view for all queries
        source = get_session_view_query(session_path)

        token_result = _execute_query(conn, TOKEN_USAGE_QUERY_V2.format(source=source))
        if not token_result:
            return SessionMetricsResponse()
        tokens = _parse_token_usage(token_result)

        model_tokens_result = _execute_query_all(
            conn, TOKEN_USAGE_BY_MODEL_QUERY_V2.format(source=source)
        )

        count_result = _execute_query(conn, MESSAGE_COUNT_QUERY_V2.format(source=source), (0, 0, 0))
        message_count = count_result[0] if count_result else 0

        tool_result = _execute_query_all(conn, TOOL_USAGE_QUERY_V2.format(source=source))
        tool_calls = sum(row[1] for row in tool_result)

        time_result = _execute_query(conn, SESSION_TIMERANGE_QUERY_V2.format(source=source))
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

        # Include subagent token usage and costs using batch query (Priority 2.4)
        subagent_files = get_subagent_files_for_session(project_hash, session_id)
        if subagent_files:
            sub_tokens, sub_cost, sub_models = get_batch_subagent_metrics(subagent_files)
            tokens.input_tokens += sub_tokens.input_tokens
            tokens.output_tokens += sub_tokens.output_tokens
            tokens.cache_creation_input_tokens += sub_tokens.cache_creation_input_tokens
            tokens.cache_read_input_tokens += sub_tokens.cache_read_input_tokens

            # Distribute subagent cost (simplified - add to total)
            # For detailed breakdown we'd need per-model costs from subagents
            total_cost.input_cost += sub_cost * 0.5  # Rough approximation
            total_cost.output_cost += sub_cost * 0.5

            for model in sub_models:
                if model not in models_used:
                    models_used.append(model)

        cache_hit_rate = calculate_cache_hit_rate(
            tokens.cache_read_input_tokens,
            tokens.cache_creation_input_tokens,
            tokens.input_tokens,
        )

        # Count errors from main session and subagents using batch query
        error_count = _get_error_count(conn, session_path, source)
        if subagent_files:
            error_count += get_batch_error_count(subagent_files)

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


def _get_subagent_details(
    conn: DuckDBPyConnection,
    project_hash: str,
    session_id: str,
    agent_id: str,
) -> tuple[str, datetime | None, TokenUsage, int]:
    """Get details for a subagent from its log file.

    Uses session views for reduced I/O (Priority 2.3).

    Returns: (status, end_time, tokens, tool_calls)
    """
    subagent_path = get_subagent_path_for_session(project_hash, session_id, agent_id)
    if not subagent_path or not subagent_path.exists():
        return ("unknown", None, TokenUsage(), 0)

    # Use session view for all subagent queries
    source = get_session_view_query(subagent_path)

    # Get token usage
    token_result = _execute_query(conn, TOKEN_USAGE_QUERY_V2.format(source=source))
    tokens = _parse_token_usage(token_result)

    # Get tool call count
    tool_result = _execute_query_all(conn, TOOL_USAGE_QUERY_V2.format(source=source))
    tool_calls = sum(row[1] for row in tool_result)

    # Get time range to determine end_time and status
    time_result = _execute_query(conn, SESSION_TIMERANGE_QUERY_V2.format(source=source))
    end_time = _parse_timestamp(time_result[1]) if time_result and time_result[1] else None

    status = "completed" if end_time else "running"

    return (status, end_time, tokens, tool_calls)


def get_session_subagents(project_hash: str, session_id: str) -> SubagentListResponse:
    """Get subagents spawned in a session with full details.

    Uses session views for reduced I/O (Priority 2.3).
    """
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return SubagentListResponse()

    with get_connection() as conn:
        # Use session view for main session query
        source = get_session_view_query(session_path)

        # Get subagent calls with proper agent IDs from progress entries
        result = _execute_query_all(
            conn, SUBAGENT_CALLS_WITH_AGENT_ID_QUERY_V2.format(source=source)
        )

        subagents = []
        for row in result:
            if not row[0]:
                continue

            agent_id = row[0]
            subagent_type = row[2] or "unknown"
            description = row[3]
            start_time = _parse_timestamp(row[5]) if len(row) > 5 else None

            # Get additional details from subagent log file
            status, end_time, tokens, tool_calls = _get_subagent_details(
                conn, project_hash, session_id, agent_id
            )

            subagents.append(
                SubagentResponse(
                    agent_id=agent_id,
                    subagent_type=subagent_type,
                    description=description,
                    status=status,
                    start_time=start_time,
                    end_time=end_time,
                    tokens=tokens,
                    tool_calls=tool_calls,
                )
            )

        return SubagentListResponse(subagents=subagents, total_count=len(subagents))


def get_session_skills(project_hash: str, session_id: str) -> SkillsResponse:
    """Get skills invoked in a session.

    Uses session views for reduced I/O (Priority 2.3).
    """
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return SkillsResponse()

    with get_connection() as conn:
        source = get_session_view_query(session_path)
        result = _execute_query_all(conn, SKILL_CALLS_QUERY_V2.format(source=source))

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
    """Get code changes made in a session.

    Uses session views for reduced I/O (Priority 2.3).
    """
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        return CodeChangesResponse()

    with get_connection() as conn:
        source = get_session_view_query(session_path)
        result = _execute_query_all(conn, CODE_CHANGES_QUERY_V2.format(source=source))

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


# _normalize_datetime is now imported from utils.datetime (Priority 4.5)


def get_project_total_metrics(
    project_hash: str, session_ids: list[str] | None = None
) -> dict[str, Any]:
    """Get aggregated metrics for a project using optimized glob query."""
    from .database import get_project_dir

    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return {}

    # Use glob-based query for faster aggregation
    glob_pattern = str(project_dir / "*.jsonl")

    with get_connection() as conn:
        try:
            result = conn.execute(
                AGGREGATE_PROJECT_SESSIONS_QUERY.format(glob_pattern=glob_pattern)
            ).fetchone()

            if not result or result[0] == 0:
                return {}

            session_count = result[0]
            input_tokens = result[1] or 0
            output_tokens = result[2] or 0
            cache_creation = result[3] or 0
            cache_read = result[4] or 0
            first_activity = _parse_timestamp(result[5])
            last_activity = _parse_timestamp(result[6])

            # Get token usage by model for accurate cost calculation
            model_rows = _execute_query_all(
                conn, TOKEN_USAGE_BY_MODEL_GLOB_QUERY.format(paths=f"'{glob_pattern}'")
            )

            total_cost = 0.0
            for row in model_rows:
                model = row[0]
                if model:
                    model_tokens = TokenUsage(
                        input_tokens=row[1] or 0,
                        output_tokens=row[2] or 0,
                        cache_creation_input_tokens=row[3] or 0,
                        cache_read_input_tokens=row[4] or 0,
                    )
                    model_cost = calculate_cost(model_tokens, model)
                    total_cost += model_cost.total_cost

            # Add subagent costs
            subagent_pattern = str(project_dir / "**/agent-*.jsonl")
            subagent_model_rows = _execute_query_all(
                conn, TOKEN_USAGE_BY_MODEL_GLOB_QUERY.format(paths=f"'{subagent_pattern}'")
            )
            for row in subagent_model_rows:
                model = row[0]
                if model:
                    sub_tokens = TokenUsage(
                        input_tokens=row[1] or 0,
                        output_tokens=row[2] or 0,
                        cache_creation_input_tokens=row[3] or 0,
                        cache_read_input_tokens=row[4] or 0,
                    )
                    input_tokens += sub_tokens.input_tokens
                    output_tokens += sub_tokens.output_tokens
                    cache_creation += sub_tokens.cache_creation_input_tokens
                    cache_read += sub_tokens.cache_read_input_tokens
                    sub_cost = calculate_cost(sub_tokens, model)
                    total_cost += sub_cost.total_cost

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
                "session_count": session_count,
            }

        except Exception:
            # Fall back to old method if glob query fails
            return _get_project_total_metrics_fallback(project_hash, session_ids)


def _get_project_total_metrics_fallback(
    project_hash: str, session_ids: list[str] | None = None
) -> dict[str, Any]:
    """Fallback method for project metrics using individual session queries."""
    if session_ids is None:
        sessions = list_sessions(project_hash)
        session_ids = [s["session_id"] for s in sessions if s["session_id"]]

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

        start = parse_timestamp(summary.start_time)
        if start and (first_activity is None or start < first_activity):
            first_activity = start

        end = parse_timestamp(summary.end_time)
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


def get_all_projects_metrics() -> dict[str, dict[str, Any]]:
    """Get aggregated metrics for ALL projects in a single query.

    This replaces the N+1 pattern where we iterate through each project
    and then each session to calculate metrics.

    Returns:
        dict mapping project_hash -> metrics dict
    """
    from .database import PROJECTS_DIR

    if not PROJECTS_DIR.exists():
        return {}

    glob_pattern = str(PROJECTS_DIR / "*/*.jsonl")

    with get_connection() as conn:
        try:
            results = conn.execute(
                AGGREGATE_ALL_PROJECTS_QUERY.format(glob_pattern=glob_pattern)
            ).fetchall()

            metrics_by_project: dict[str, dict[str, Any]] = {}

            for row in results:
                project_hash = row[0]
                if not project_hash:
                    continue

                session_count = row[1] or 0
                input_tokens = row[2] or 0
                output_tokens = row[3] or 0
                cache_creation = row[4] or 0
                cache_read = row[5] or 0
                first_activity = _parse_timestamp(row[6])
                last_activity = _parse_timestamp(row[7])
                models_used = row[8] or []

                # Calculate cost per model
                total_cost = 0.0
                for model in models_used:
                    if model:
                        # Get per-model tokens for this project
                        model_query = f"""
                        WITH file_data AS (
                            SELECT message
                            FROM read_json_auto(
                                '{PROJECTS_DIR}/{project_hash}/*.jsonl',
                                filename=true,
                                maximum_object_size=104857600,
                                ignore_errors=true,
                                union_by_name=true
                            )
                            WHERE type = 'assistant'
                              AND message.model = '{model}'
                              AND message.usage IS NOT NULL
                              AND message.id IS NOT NULL
                        ),
                        deduplicated AS (
                            SELECT DISTINCT ON (message.id)
                                message.usage.input_tokens as input_tokens,
                                message.usage.output_tokens as output_tokens,
                                message.usage.cache_creation_input_tokens as cache_creation,
                                message.usage.cache_read_input_tokens as cache_read
                            FROM file_data
                        )
                        SELECT
                            COALESCE(SUM(input_tokens), 0),
                            COALESCE(SUM(output_tokens), 0),
                            COALESCE(SUM(cache_creation), 0),
                            COALESCE(SUM(cache_read), 0)
                        FROM deduplicated
                        """
                        model_result = conn.execute(model_query).fetchone()
                        if model_result:
                            model_tokens = TokenUsage(
                                input_tokens=model_result[0] or 0,
                                output_tokens=model_result[1] or 0,
                                cache_creation_input_tokens=model_result[2] or 0,
                                cache_read_input_tokens=model_result[3] or 0,
                            )
                            model_cost = calculate_cost(model_tokens, model)
                            total_cost += model_cost.total_cost

                # Include subagent metrics for this project
                subagent_pattern = str(PROJECTS_DIR / project_hash / "**/agent-*.jsonl")
                subagent_model_rows = _execute_query_all(
                    conn, TOKEN_USAGE_BY_MODEL_GLOB_QUERY.format(paths=f"'{subagent_pattern}'")
                )
                for sub_row in subagent_model_rows:
                    model = sub_row[0]
                    if model:
                        sub_tokens = TokenUsage(
                            input_tokens=sub_row[1] or 0,
                            output_tokens=sub_row[2] or 0,
                            cache_creation_input_tokens=sub_row[3] or 0,
                            cache_read_input_tokens=sub_row[4] or 0,
                        )
                        input_tokens += sub_tokens.input_tokens
                        output_tokens += sub_tokens.output_tokens
                        cache_creation += sub_tokens.cache_creation_input_tokens
                        cache_read += sub_tokens.cache_read_input_tokens
                        sub_cost = calculate_cost(sub_tokens, model)
                        total_cost += sub_cost.total_cost

                metrics_by_project[project_hash] = {
                    "tokens": {
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cache_creation_input_tokens": cache_creation,
                        "cache_read_input_tokens": cache_read,
                    },
                    "total_cost": total_cost,
                    "first_activity": first_activity,
                    "last_activity": last_activity,
                    "session_count": session_count,
                }

            return metrics_by_project

        except Exception:
            # Return empty dict on error - caller can fall back
            return {}


def get_batch_subagent_metrics(
    subagent_paths: list[Path],
) -> tuple[TokenUsage, float, list[str]]:
    """Get combined token usage, cost, and models from multiple subagent files.

    Uses a single DuckDB query instead of iterating through each file.

    Returns:
        tuple of (TokenUsage, total_cost, models_used)
    """
    if not subagent_paths:
        return TokenUsage(), 0.0, []

    paths_str = ", ".join(f"'{p}'" for p in subagent_paths)

    with get_connection() as conn:
        try:
            model_rows = conn.execute(
                TOKEN_USAGE_BY_MODEL_GLOB_QUERY.format(paths=f"[{paths_str}]")
            ).fetchall()

            tokens = TokenUsage()
            total_cost = 0.0
            models_used: list[str] = []

            for row in model_rows:
                model = row[0]
                if not model:
                    continue

                sub_tokens = TokenUsage(
                    input_tokens=row[1] or 0,
                    output_tokens=row[2] or 0,
                    cache_creation_input_tokens=row[3] or 0,
                    cache_read_input_tokens=row[4] or 0,
                )

                tokens.input_tokens += sub_tokens.input_tokens
                tokens.output_tokens += sub_tokens.output_tokens
                tokens.cache_creation_input_tokens += sub_tokens.cache_creation_input_tokens
                tokens.cache_read_input_tokens += sub_tokens.cache_read_input_tokens

                sub_cost = calculate_cost(sub_tokens, model)
                total_cost += sub_cost.total_cost

                if model not in models_used:
                    models_used.append(model)

            return tokens, total_cost, models_used

        except Exception:
            # Fall back to sequential method
            tokens = TokenUsage()
            total_cost = _accumulate_subagent_data(conn, subagent_paths, tokens, None, None)
            return tokens, total_cost, []


def get_batch_error_count(paths: list[Path]) -> int:
    """Get total error count across multiple files in a single query."""
    if not paths:
        return 0

    paths_str = ", ".join(f"'{p}'" for p in paths)

    with get_connection() as conn:
        try:
            result = conn.execute(ERROR_COUNT_GLOB_QUERY.format(paths=f"[{paths_str}]")).fetchone()
            return result[0] if result else 0
        except Exception:
            # Fall back to sequential
            return sum(_get_error_count(conn, p) for p in paths)

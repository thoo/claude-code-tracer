"""Session-related API endpoints."""

import base64
from datetime import datetime
from pathlib import Path

import orjson
from fastapi import APIRouter, HTTPException, Query

from ..models.entries import TokenUsage, ToolUse
from ..models.responses import (
    CodeChangesResponse,
    CommandsResponse,
    CommandsSummary,
    CostBreakdown,
    ErrorsResponse,
    MessageDetailResponse,
    MessageFilterOptions,
    MessageListResponse,
    MessageResponse,
    ProjectListResponse,
    ProjectResponse,
    SessionListResponse,
    SessionMetricsResponse,
    SessionSummary,
    SkillsResponse,
    SubagentListResponse,
    ToolFilterOption,
    ToolUsageResponse,
    ToolUsageStats,
    UserCommand,
)
from ..services.async_io import (
    get_all_projects_metrics_async,
    get_project_total_metrics_async,
    get_session_code_changes_async,
    get_session_errors_async,
    get_session_metrics_async,
    get_session_skills_async,
    get_session_subagents_async,
    get_session_tool_usage_async,
    list_projects_async,
    list_sessions_async,
    parse_session_summary_async,
)
from ..services.cache import (
    cache_filter_options,
    cache_metrics,
    cache_subagents,
    cache_tool_usage,
    get_cached_filter_options,
    get_cached_metrics,
    get_cached_subagents,
    get_cached_tool_usage,
)
from ..services.database import (
    get_connection,
    get_session_path,
    get_session_view_query,
    session_has_messages,
)
from ..services.queries import (
    ERROR_COUNT_QUERY_V2,
    MESSAGE_BY_INDEX_QUERY,
    MESSAGE_DETAIL_QUERY,
    MESSAGES_COMPREHENSIVE_QUERY_V2,
    TOOL_NAMES_LIST_QUERY_V2,
    USER_COMMANDS_QUERY_V2,
)
from ..utils.datetime import normalize_datetime

router = APIRouter(prefix="/api", tags=["sessions"])


def require_session_path(project_hash: str, session_id: str) -> Path:
    """Get session path and raise 404 if it doesn't exist."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    return session_path


# ============================================================================
# Cursor-based Pagination Utilities (Priority 3.1)
# ============================================================================


def encode_cursor(timestamp: datetime | str, uuid: str) -> str:
    """Encode a timestamp and uuid into a base64 cursor string.

    The cursor format is: base64(timestamp_iso|uuid)

    Args:
        timestamp: Either a datetime object or an ISO format string
        uuid: The message UUID
    """
    if timestamp is None:
        ts_str = ""
    elif isinstance(timestamp, str):
        ts_str = timestamp  # Already an ISO string from DuckDB
    else:
        ts_str = timestamp.isoformat()
    cursor_data = f"{ts_str}|{uuid}"
    return base64.urlsafe_b64encode(cursor_data.encode()).decode()


def decode_cursor(cursor: str) -> tuple[datetime | None, str | None]:
    """Decode a base64 cursor string into timestamp and uuid.

    Returns (timestamp, uuid) or (None, None) if invalid.
    """
    try:
        cursor_data = base64.urlsafe_b64decode(cursor.encode()).decode()
        parts = cursor_data.split("|", 1)
        if len(parts) != 2:
            return None, None

        ts_str, uuid_str = parts
        timestamp = datetime.fromisoformat(ts_str) if ts_str else None
        return timestamp, uuid_str
    except (ValueError, UnicodeDecodeError):
        return None, None


@router.get("/projects", response_model=ProjectListResponse)
async def get_projects() -> ProjectListResponse:
    """List all projects from ~/.claude/projects/.

    Optimized to fetch all project metrics in a single query instead of
    N+1 queries (one per project × sessions per project).

    Uses background index for project discovery (Priority 4.1) and
    async I/O for non-blocking operation (Priority 4.2).
    """
    projects_data = await list_projects_async()

    # Get all project metrics in one batch query (Priority 2.1 optimization)
    all_metrics = await get_all_projects_metrics_async()

    projects = []
    for proj in projects_data:
        project_hash = str(proj["path_hash"])
        project_path = str(proj["project_path"])

        # Use batch metrics if available, otherwise fall back to individual query
        if project_hash in all_metrics:
            metrics = all_metrics[project_hash]
        else:
            metrics = await get_project_total_metrics_async(project_hash)

        tokens_data = metrics.get("tokens", {})

        projects.append(
            ProjectResponse(
                path_hash=project_hash,
                project_path=project_path,
                session_count=metrics.get("session_count", proj.get("session_count", 0)),
                tokens=TokenUsage(
                    input_tokens=tokens_data.get("input_tokens", 0),
                    output_tokens=tokens_data.get("output_tokens", 0),
                    cache_creation_input_tokens=tokens_data.get("cache_creation_input_tokens", 0),
                    cache_read_input_tokens=tokens_data.get("cache_read_input_tokens", 0),
                ),
                total_cost=metrics.get("total_cost", 0.0),
                last_activity=metrics.get("last_activity"),
                first_activity=metrics.get("first_activity"),
            )
        )

    # Sort by last activity (most recent first)
    projects.sort(
        key=lambda p: normalize_datetime(p.last_activity or p.first_activity),
        reverse=True,
    )

    return ProjectListResponse(projects=projects)


@router.get("/projects/{project_hash}/sessions", response_model=SessionListResponse)
async def get_project_sessions(project_hash: str) -> SessionListResponse:
    """List all sessions for a project.

    Uses background index for session discovery (Priority 4.1) and
    async I/O for non-blocking operation (Priority 4.2).
    """
    sessions_data = await list_sessions_async(project_hash)

    if not sessions_data:
        return SessionListResponse(sessions=[], total=0)

    sessions = []
    for sess in sessions_data:
        session_id = sess["session_id"]
        if not session_id:
            continue
        summary = await parse_session_summary_async(project_hash, session_id)
        if summary:
            summary = summary.model_copy()
            summary.slug = sess.get("slug")
            sessions.append(summary)

    # Sort by start time (most recent first), normalizing timezone for comparison
    sessions.sort(key=lambda s: normalize_datetime(s.start_time), reverse=True)

    return SessionListResponse(sessions=sessions, total=len(sessions))


@router.get("/projects/{project_hash}/metrics", response_model=SessionMetricsResponse)
async def get_project_metrics(project_hash: str) -> SessionMetricsResponse:
    """Get aggregated metrics for all sessions in a project.

    Uses async I/O for non-blocking operation (Priority 4.2).
    """
    sessions_data = await list_sessions_async(project_hash)

    if not sessions_data:
        return SessionMetricsResponse()

    # Aggregate metrics across all sessions
    total_input_tokens = 0
    total_output_tokens = 0
    total_cache_creation = 0
    total_cache_read = 0
    total_input_cost = 0.0
    total_output_cost = 0.0
    total_cache_creation_cost = 0.0
    total_cache_read_cost = 0.0
    total_duration = 0
    total_messages = 0
    total_tool_calls = 0
    total_errors = 0
    all_models: set[str] = set()
    total_interruptions = 0
    total_commands = 0

    for sess in sessions_data:
        session_id = sess["session_id"]
        if not session_id:
            continue
        metrics = await get_session_metrics_async(project_hash, session_id)
        if metrics:
            total_input_tokens += metrics.tokens.input_tokens
            total_output_tokens += metrics.tokens.output_tokens
            total_cache_creation += metrics.tokens.cache_creation_input_tokens
            total_cache_read += metrics.tokens.cache_read_input_tokens
            total_input_cost += metrics.cost.input_cost
            total_output_cost += metrics.cost.output_cost
            total_cache_creation_cost += metrics.cost.cache_creation_cost
            total_cache_read_cost += metrics.cost.cache_read_cost
            total_duration += metrics.duration_seconds
            total_messages += metrics.message_count
            total_tool_calls += metrics.tool_calls
            total_errors += metrics.error_count
            all_models.update(metrics.models_used)
            # Track interruptions for rate calculation
            if metrics.interruption_rate > 0:
                # Estimate commands from interruption rate
                estimated_commands = metrics.message_count // 2  # rough estimate
                total_interruptions += int(estimated_commands * metrics.interruption_rate / 100)
                total_commands += estimated_commands

    # Calculate cache hit rate
    total_cache_tokens = total_cache_creation + total_cache_read
    total_all_input = total_input_tokens + total_cache_tokens
    cache_hit_rate = (total_cache_read / total_all_input * 100) if total_all_input > 0 else 0.0

    # Calculate interruption rate
    interruption_rate = (total_interruptions / total_commands * 100) if total_commands > 0 else 0.0

    return SessionMetricsResponse(
        tokens=TokenUsage(
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            cache_creation_input_tokens=total_cache_creation,
            cache_read_input_tokens=total_cache_read,
        ),
        cost=CostBreakdown(
            input_cost=total_input_cost,
            output_cost=total_output_cost,
            cache_creation_cost=total_cache_creation_cost,
            cache_read_cost=total_cache_read_cost,
        ),
        duration_seconds=total_duration,
        message_count=total_messages,
        tool_calls=total_tool_calls,
        error_count=total_errors,
        cache_hit_rate=cache_hit_rate,
        models_used=sorted(all_models),
        interruption_rate=interruption_rate,
    )


@router.get("/projects/{project_hash}/tools", response_model=ToolUsageResponse)
async def get_project_tools(project_hash: str) -> ToolUsageResponse:
    """Get aggregated tool usage for all sessions in a project.

    Uses async I/O for non-blocking operation (Priority 4.2).
    """
    sessions_data = await list_sessions_async(project_hash)

    if not sessions_data:
        return ToolUsageResponse(tools=[], total_calls=0)

    # Aggregate tool usage across all sessions
    tool_counts: dict[str, int] = {}

    for sess in sessions_data:
        session_id = sess["session_id"]
        if not session_id:
            continue
        tools_data = await get_session_tool_usage_async(project_hash, session_id)
        if tools_data:
            for tool in tools_data.tools:
                tool_counts[tool.name] = tool_counts.get(tool.name, 0) + tool.count

    # Convert to response format
    tools = [
        ToolUsageStats(name=name, count=count)
        for name, count in sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    total_calls = sum(tool_counts.values())

    return ToolUsageResponse(tools=tools, total_calls=total_calls)


@router.get("/sessions/{project_hash}/{session_id}", response_model=SessionSummary)
async def get_session(project_hash: str, session_id: str) -> SessionSummary:
    """Get session details.

    Uses async I/O for non-blocking operation (Priority 4.2).
    """
    summary = await parse_session_summary_async(project_hash, session_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return summary


@router.get("/sessions/{project_hash}/{session_id}/messages", response_model=MessageListResponse)
async def get_session_messages(
    project_hash: str,
    session_id: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    tool_filter: str | None = Query(default=None, alias="tool"),
    error_only: bool = Query(default=False),
    search: str | None = Query(default=None),
    cursor: str | None = Query(default=None, description="Cursor for keyset pagination"),
) -> MessageListResponse:
    """Get paginated messages for a session with filtering.

    Supports both page-based and cursor-based pagination:
    - page/per_page: Traditional offset pagination (default)
    - cursor: Keyset pagination using timestamp|uuid (more efficient for deep pages)

    Supports filtering by:
    - type: 'assistant', 'user', 'hook', or 'tool_result'
    - tool: filter by tool name (for assistant messages with that tool)
    - error_only: only show messages with errors (tool_result messages)
    - search: text search in message content (case-insensitive)

    Optimizations (Phase 3):
    - Uses session views to avoid re-parsing JSONL files (Priority 2.3)
    - Uses lazy counting (limit+1 pattern) to avoid expensive COUNT queries (Priority 3.2)
    - Supports keyset pagination for efficient deep pagination (Priority 3.1)
    """
    session_path = require_session_path(project_hash, session_id)

    # Check if session has actual message data (not just metadata)
    if not session_has_messages(session_path):
        return MessageListResponse(
            messages=[],
            total=0,
            page=page,
            per_page=per_page,
            total_pages=0,
            next_cursor=None,
            has_more=False,
        )

    # Build WHERE clause for filtering
    where_conditions = []
    if type_filter:
        where_conditions.append(f"msg_type = '{type_filter}'")
    if tool_filter:
        where_conditions.append(f"tool_names LIKE '%{tool_filter}%'")
    if error_only:
        where_conditions.append("is_error = true")
    if search:
        # Escape single quotes in search term and do case-insensitive search
        escaped_search = search.replace("'", "''")
        where_conditions.append(f"LOWER(CAST(message AS VARCHAR)) LIKE LOWER('%{escaped_search}%')")

    where_clause = ""
    if where_conditions:
        where_clause = "WHERE " + " AND ".join(where_conditions)

    # Determine pagination mode: cursor-based or page-based
    use_cursor = cursor is not None
    cursor_ts, cursor_uuid = (None, None)

    if use_cursor and cursor:
        cursor_ts, cursor_uuid = decode_cursor(cursor)
        if cursor_ts is None or cursor_uuid is None:
            raise HTTPException(status_code=400, detail="Invalid cursor format")
        offset = 0  # Not used in cursor mode
    else:
        offset = (page - 1) * per_page

    # Get session view or fall back to direct file read (Priority 2.3 optimization)
    source = get_session_view_query(session_path)

    with get_connection() as conn:
        try:
            # Get paginated messages using comprehensive V2 query with session view
            query = MESSAGES_COMPREHENSIVE_QUERY_V2.format(
                source=source,
                sort_dir="ASC",
                where_clause=where_clause,
            )

            # Lazy counting optimization (Priority 3.2):
            # Request limit+1 rows to determine if there are more results
            fetch_limit = per_page + 1

            if use_cursor:
                # Keyset pagination (Priority 3.1):
                # Cast both sides to TIMESTAMP for proper comparison:
                # - timestamp column may be VARCHAR (from JSONL) or TIMESTAMP (from tests)
                # - cursor string is ISO format which DuckDB parses automatically
                cursor_ts_str = cursor_ts.isoformat() if cursor_ts else ""
                paginated_query = f"""
                WITH comprehensive AS ({query})
                SELECT * FROM comprehensive
                WHERE CAST(timestamp AS TIMESTAMP) > TIMESTAMP '{cursor_ts_str}'
                   OR (CAST(timestamp AS TIMESTAMP) = TIMESTAMP '{cursor_ts_str}' AND CAST(uuid AS VARCHAR) > '{cursor_uuid}')
                ORDER BY timestamp ASC, uuid ASC
                LIMIT {fetch_limit}
                """
            else:
                # Traditional offset pagination
                paginated_query = f"""
                WITH comprehensive AS ({query})
                SELECT * FROM comprehensive
                WHERE row_num > {offset}
                LIMIT {fetch_limit}
                """

            result = conn.execute(paginated_query).fetchall()

            # Determine if there are more results based on whether we got limit+1 rows
            has_more = len(result) > per_page
            if has_more:
                result = result[:per_page]  # Return only requested amount

            # Calculate next cursor if there are more results
            next_cursor = None
            if has_more and result:
                last_row = result[-1]
                # Row indices: 0=uuid, 1=msg_type, 2=timestamp, ...
                last_timestamp = last_row[2]
                last_uuid = last_row[0]
                next_cursor = encode_cursor(last_timestamp, str(last_uuid))

            # Calculate total (only needed for page-based pagination UI)
            if use_cursor:
                # In cursor mode, total is not needed (use has_more instead)
                total = 0
                total_pages = 0
            elif page == 1 and not has_more:
                # All results fit on first page
                total = len(result)
                total_pages = 1
            elif page == 1:
                # First page with more results - need count for UI
                count_query = f"""
                WITH comprehensive AS ({query})
                SELECT COUNT(*) FROM comprehensive
                """
                total = conn.execute(count_query).fetchone()[0]
                total_pages = (total + per_page - 1) // per_page if total > 0 else 1
            else:
                # Subsequent pages - estimate total
                total = offset + len(result) + (1 if has_more else 0)
                total_pages = (total + per_page - 1) // per_page if total > 0 else 1

        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    messages = [_parse_comprehensive_message_row(row) for row in result]

    return MessageListResponse(
        messages=messages,
        total=total,
        page=page if not use_cursor else 0,
        per_page=per_page,
        total_pages=total_pages,
        next_cursor=next_cursor,
        has_more=has_more,
    )


@router.get(
    "/sessions/{project_hash}/{session_id}/messages/filters", response_model=MessageFilterOptions
)
async def get_session_message_filters(
    project_hash: str,
    session_id: str,
) -> MessageFilterOptions:
    """Get available filter options for session messages.

    Uses session views (Priority 2.3) and query result caching (Priority 3.6).
    Results are cached until the session file changes.
    """
    session_path = require_session_path(project_hash, session_id)

    # Check if session has actual message data (not just metadata)
    if not session_has_messages(session_path):
        return MessageFilterOptions(
            types=["assistant", "user", "hook", "tool_result"],
            tools=[],
            error_count=0,
        )

    # Check cache first
    cached = get_cached_filter_options(session_path)
    if cached is not None:
        return cached

    # Use session view for efficient querying
    source = get_session_view_query(session_path)

    with get_connection() as conn:
        try:
            # Get tool names with counts using V2 query with session view
            tools_result = conn.execute(TOOL_NAMES_LIST_QUERY_V2.format(source=source)).fetchall()
            tools = [ToolFilterOption(name=row[0], count=row[1]) for row in tools_result]

            # Get error count using V2 query with session view
            error_result = conn.execute(ERROR_COUNT_QUERY_V2.format(source=source)).fetchone()
            error_count = error_result[0] if error_result else 0
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    result = MessageFilterOptions(
        types=["assistant", "user", "subagent", "hook", "tool_result"],
        tools=tools,
        error_count=error_count,
    )

    # Cache the result
    cache_filter_options(session_path, result)
    return result


@router.get(
    "/sessions/{project_hash}/{session_id}/messages/{message_uuid}",
    response_model=MessageDetailResponse,
)
async def get_message_detail(
    project_hash: str,
    session_id: str,
    message_uuid: str,
) -> MessageDetailResponse:
    """Get detailed information about a specific message."""
    session_path = require_session_path(project_hash, session_id)

    with get_connection() as conn:
        try:
            result = conn.execute(
                MESSAGE_DETAIL_QUERY.format(path=str(session_path), uuid=message_uuid)
            ).fetchone()

            if not result:
                raise HTTPException(status_code=404, detail="Message not found")

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    return _parse_message_detail_row(result)


@router.get(
    "/sessions/{project_hash}/{session_id}/messages/by-index/{index}",
    response_model=MessageDetailResponse,
)
async def get_message_by_index(
    project_hash: str,
    session_id: str,
    index: int,
) -> MessageDetailResponse:
    """Get message by its index (1-based) for prev/next navigation."""
    session_path = require_session_path(project_hash, session_id)

    with get_connection() as conn:
        try:
            result = conn.execute(
                MESSAGE_BY_INDEX_QUERY.format(path=str(session_path), index=index)
            ).fetchone()

            if not result:
                raise HTTPException(status_code=404, detail="Message not found")

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    return _parse_message_detail_row(result)


def _parse_assistant_content(raw_content: str | list) -> tuple[str | None, list[ToolUse]]:
    """Extract text content and tool uses from assistant message content."""
    if isinstance(raw_content, str):
        return raw_content, []

    if not isinstance(raw_content, list):
        return None, []

    text_parts = []
    tools = []
    for block in raw_content:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "text":
            text_parts.append(block.get("text", ""))
        elif block_type == "tool_use":
            tools.append(
                ToolUse(
                    type="tool_use",
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    input=block.get("input", {}),
                )
            )

    content = "\n".join(text_parts) if text_parts else None
    return content, tools


def _parse_user_content(raw_content: str | list | None) -> tuple[str | None, list[dict], bool]:
    """Extract text content, tool results, and error status from user message content."""
    if isinstance(raw_content, str):
        return raw_content, [], False

    if not isinstance(raw_content, list):
        return None, [], False

    content = None
    tool_results = []
    is_error = False

    for block in raw_content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_result":
            tool_results.append(block)
            if block.get("is_error"):
                is_error = True
        elif isinstance(block.get("text"), str):
            content = block.get("text")

    if not content and not tool_results:
        content = str(raw_content)

    return content, tool_results, is_error


def _parse_message_detail_row(row: tuple) -> MessageDetailResponse:
    """Parse a message detail query row into MessageDetailResponse.

    Row format:
    - row[0]: uuid
    - row[1]: type
    - row[2]: timestamp
    - row[3]: message (dict)
    - row[4]: session_id
    - row[5]: cwd
    - row[6]: row_num (1-based index)
    - row[7]: total count
    """
    msg = row[3] or {}
    msg_type = row[1]

    if msg_type == "assistant":
        content, tools = _parse_assistant_content(msg.get("content", []))
        return MessageDetailResponse(
            uuid=str(row[0]),
            message_id=msg.get("id"),
            type=msg_type,
            timestamp=row[2],
            content=content,
            model=msg.get("model"),
            tokens=_parse_usage_data(msg.get("usage")),
            tools=tools,
            tool_results=[],
            is_error=False,
            session_id=str(row[4]),
            cwd=row[5],
            message_index=row[6],
            total_messages=row[7],
        )

    content, tool_results, is_error = _parse_user_content(msg.get("content"))
    return MessageDetailResponse(
        uuid=str(row[0]),
        message_id=None,
        type=msg_type,
        timestamp=row[2],
        content=content,
        model=None,
        tokens=TokenUsage(),
        tools=[],
        tool_results=tool_results,
        is_error=is_error,
        session_id=str(row[4]),
        cwd=row[5],
        message_index=row[6],
        total_messages=row[7],
    )


def _parse_usage_data(usage_data: str | dict | None) -> TokenUsage:
    """Parse usage data into TokenUsage, handling both string and dict formats."""
    if not usage_data:
        return TokenUsage()

    # Parse JSON string if needed
    if isinstance(usage_data, str):
        try:
            usage_data = orjson.loads(usage_data)
        except orjson.JSONDecodeError:
            return TokenUsage()

    if not isinstance(usage_data, dict):
        return TokenUsage()

    return TokenUsage(
        input_tokens=usage_data.get("input_tokens", 0),
        output_tokens=usage_data.get("output_tokens", 0),
        cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
    )


def _extract_tool_use_id(msg_content: dict | str | None) -> str | None:
    """Extract tool_use_id from a tool_result message content.

    Tool result messages have content blocks with tool_use_id field.
    """
    if msg_content is None:
        return None

    # If it's a string, try to parse it as JSON
    if isinstance(msg_content, str):
        try:
            msg_content = orjson.loads(msg_content)
        except (orjson.JSONDecodeError, ValueError):
            return None

    if not isinstance(msg_content, dict):
        return None

    raw_content = msg_content.get("content")

    # Check for tool_use_id at the top level of content blocks
    if isinstance(raw_content, list):
        for block in raw_content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                tool_use_id = block.get("tool_use_id")
                if tool_use_id:
                    return str(tool_use_id)

    return None


def _extract_tools_summary(msg_content: dict | str | None) -> list[ToolUse]:
    """Extract tool uses (with IDs) from assistant message content.

    Only extracts id and name to keep the response lightweight.
    """
    if msg_content is None:
        return []

    # If it's a string, try to parse it as JSON
    if isinstance(msg_content, str):
        try:
            msg_content = orjson.loads(msg_content)
        except (orjson.JSONDecodeError, ValueError):
            return []

    if not isinstance(msg_content, dict):
        return []

    raw_content = msg_content.get("content")
    tools = []

    if isinstance(raw_content, list):
        for block in raw_content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_id = block.get("id", "")
                tool_name = block.get("name", "")
                if tool_id or tool_name:
                    tools.append(
                        ToolUse(
                            type="tool_use",
                            id=str(tool_id) if tool_id else "",
                            name=str(tool_name) if tool_name else "",
                            input={},  # Keep empty to reduce payload
                        )
                    )

    return tools


def _parse_comprehensive_message_row(row: tuple) -> MessageResponse:
    """Parse a comprehensive query row into a MessageResponse.

    Row format from MESSAGES_COMPREHENSIVE_QUERY:
    - row[0]: uuid
    - row[1]: msg_type (assistant, user, tool_result, subagent)
    - row[2]: timestamp
    - row[3]: message
    - row[4]: model
    - row[5]: usage
    - row[6]: session_id
    - row[7]: tool_names
    - row[8]: is_error
    - row[9]: row_num
    """
    msg_type = row[1]
    is_subagent = msg_type == "subagent"
    is_tool_result = msg_type == "tool_result"
    is_assistant = msg_type == "assistant"

    # Subagent content is JSON from DuckDB - keep as-is; otherwise extract and truncate
    if is_subagent:
        content_text = row[3] if row[3] else None
    else:
        raw_content = _extract_content_text(row[3])
        content_text = raw_content[:500] if raw_content else None

    # Extract tool_use_id for tool_result messages
    tool_use_id = None
    if is_tool_result:
        tool_use_id = _extract_tool_use_id(row[3])

    # Extract tool IDs for assistant messages with tools
    tools = []
    if is_assistant and row[7]:  # row[7] is tool_names
        tools = _extract_tools_summary(row[3])

    return MessageResponse(
        uuid=str(row[0]),
        type=msg_type,
        timestamp=row[2],
        content=content_text,
        model=row[4],
        tokens=_parse_usage_data(row[5]),
        tools=tools,
        tool_names=row[7] or "",
        tool_use_id=tool_use_id,
        has_tool_result=is_tool_result,
        is_error=bool(row[8]),
        session_id=str(row[6]),
    )


def _extract_content_text(msg_content: dict | str | None) -> str:
    """Extract text content from a message content object.

    Handles both dict (parsed) and string (JSON) message formats.
    Extracts content from text, tool_result, and tool_use blocks.
    """
    if msg_content is None:
        return ""

    # If it's a string, try to parse it as JSON
    if isinstance(msg_content, str):
        original_str = msg_content
        try:
            msg_content = orjson.loads(msg_content)
        except (orjson.JSONDecodeError, ValueError):
            # If it's not valid JSON, return the string directly
            return original_str[:500]

    if not isinstance(msg_content, dict):
        return str(msg_content)[:500] if msg_content else ""

    raw_content = msg_content.get("content")
    if isinstance(raw_content, str):
        return raw_content[:500]

    if isinstance(raw_content, list):
        text_parts = []
        for block in raw_content:
            if isinstance(block, str):
                text_parts.append(block[:200])
                continue
            if not isinstance(block, dict):
                continue

            block_type = block.get("type")
            if block_type == "text":
                # Text block from assistant or user
                text_parts.append(block.get("text", "")[:200])
            elif block_type == "thinking":
                # Thinking block from assistant - show preview
                thinking_text = block.get("thinking", "")[:150]
                if thinking_text:
                    text_parts.append(f"[Thinking: {thinking_text}...]")
            elif block_type == "tool_result":
                # Tool result block - extract the content
                result_content = block.get("content")
                if isinstance(result_content, str):
                    text_parts.append(result_content[:200])
                elif isinstance(result_content, list):
                    # Handle nested content blocks in tool results
                    for sub_block in result_content:
                        if isinstance(sub_block, dict) and sub_block.get("type") == "text":
                            text_parts.append(sub_block.get("text", "")[:100])
                        elif isinstance(sub_block, str):
                            text_parts.append(sub_block[:100])
            elif block_type == "tool_use":
                # Tool use block - show tool name and brief input preview
                tool_name = block.get("name", "unknown")
                tool_input = block.get("input", {})
                if isinstance(tool_input, dict):
                    # Extract meaningful fields for common tools
                    preview = ""
                    if "file_path" in tool_input:
                        preview = tool_input["file_path"]
                    elif "command" in tool_input:
                        preview = tool_input["command"][:100]
                    elif "pattern" in tool_input:
                        preview = tool_input["pattern"]
                    elif "query" in tool_input:
                        preview = tool_input["query"][:100]
                    elif "prompt" in tool_input:
                        preview = tool_input["prompt"][:50]
                    if preview:
                        text_parts.append(f"[{tool_name}: {preview}]")
                    else:
                        text_parts.append(f"[{tool_name}]")

        if text_parts:
            return " ".join(text_parts)

    return ""


@router.get("/sessions/{project_hash}/{session_id}/tools", response_model=ToolUsageResponse)
async def get_session_tools(project_hash: str, session_id: str) -> ToolUsageResponse:
    """Get tool usage statistics for a session.

    Uses query result caching (Priority 3.6) - results are cached until the
    session file changes (mtime-based invalidation).
    Uses async I/O for non-blocking operation (Priority 4.2).
    """
    session_path = require_session_path(project_hash, session_id)

    # Check cache first
    cached = get_cached_tool_usage(session_path)
    if cached is not None:
        return cached

    # Query and cache result
    result = await get_session_tool_usage_async(project_hash, session_id)
    cache_tool_usage(session_path, result)
    return result


@router.get("/sessions/{project_hash}/{session_id}/metrics", response_model=SessionMetricsResponse)
async def get_session_metrics_endpoint(
    project_hash: str, session_id: str
) -> SessionMetricsResponse:
    """Get detailed metrics for a session.

    Uses query result caching (Priority 3.6) - results are cached until the
    session file changes (mtime-based invalidation).
    Uses async I/O for non-blocking operation (Priority 4.2).
    """
    session_path = require_session_path(project_hash, session_id)

    # Check cache first
    cached = get_cached_metrics(session_path)
    if cached is not None:
        return cached

    # Query and cache result
    result = await get_session_metrics_async(project_hash, session_id)
    cache_metrics(session_path, result)
    return result


@router.get("/sessions/{project_hash}/{session_id}/subagents", response_model=SubagentListResponse)
async def get_session_subagents_endpoint(
    project_hash: str, session_id: str
) -> SubagentListResponse:
    """Get subagents spawned in a session.

    Uses query result caching (Priority 3.6) - results are cached until the
    session file changes (mtime-based invalidation).
    Uses async I/O for non-blocking operation (Priority 4.2).
    """
    session_path = require_session_path(project_hash, session_id)

    # Check cache first
    cached = get_cached_subagents(session_path)
    if cached is not None:
        return cached

    # Query and cache result
    result = await get_session_subagents_async(project_hash, session_id)
    cache_subagents(session_path, result)
    return result


@router.get("/sessions/{project_hash}/{session_id}/skills", response_model=SkillsResponse)
async def get_session_skills_endpoint(project_hash: str, session_id: str) -> SkillsResponse:
    """Get skills invoked in a session.

    Uses async I/O for non-blocking operation (Priority 4.2).
    """
    require_session_path(project_hash, session_id)
    return await get_session_skills_async(project_hash, session_id)


@router.get(
    "/sessions/{project_hash}/{session_id}/code-changes", response_model=CodeChangesResponse
)
async def get_session_code_changes_endpoint(
    project_hash: str, session_id: str
) -> CodeChangesResponse:
    """Get code changes made in a session.

    Uses async I/O for non-blocking operation (Priority 4.2).
    """
    require_session_path(project_hash, session_id)
    return await get_session_code_changes_async(project_hash, session_id)


@router.get("/sessions/{project_hash}/{session_id}/errors", response_model=ErrorsResponse)
async def get_session_errors_endpoint(project_hash: str, session_id: str) -> ErrorsResponse:
    """Get errors from a session.

    Uses async I/O for non-blocking operation (Priority 4.2).
    """
    require_session_path(project_hash, session_id)
    return await get_session_errors_async(project_hash, session_id)


@router.get("/sessions/{project_hash}/{session_id}/commands", response_model=CommandsResponse)
async def get_session_commands(project_hash: str, session_id: str) -> CommandsResponse:
    """Get user commands with statistics for a session.

    Optimized to use session views for reduced I/O (Priority 2.3).
    """
    session_path = require_session_path(project_hash, session_id)

    # Use session view for efficient querying
    source = get_session_view_query(session_path)

    with get_connection() as conn:
        try:
            result = conn.execute(USER_COMMANDS_QUERY_V2.format(source=source)).fetchall()
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    commands = []
    interrupted_count = 0

    for row in result:
        content = row[2]
        if content and isinstance(content, str):
            is_interrupted = row[3] if len(row) > 3 else False
            if is_interrupted:
                interrupted_count += 1

            commands.append(
                UserCommand(
                    user_message=content[:500],
                    timestamp=row[1],
                    followed_by_interruption=is_interrupted,
                )
            )

    total_commands = len(commands)
    interruption_rate = (interrupted_count / total_commands * 100) if total_commands > 0 else 0.0

    return CommandsResponse(
        commands=commands,
        summary=CommandsSummary(
            total_commands=total_commands,
            interruption_rate=interruption_rate,
        ),
    )

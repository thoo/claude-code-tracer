"""Session-related API endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..models.entries import TokenUsage
from ..models.responses import (
    CodeChangesResponse,
    CommandsResponse,
    CommandsSummary,
    CostBreakdown,
    ErrorsResponse,
    MessageListResponse,
    MessageResponse,
    ProjectListResponse,
    ProjectResponse,
    SessionListResponse,
    SessionMetricsResponse,
    SessionSummary,
    SkillsResponse,
    SubagentListResponse,
    ToolUsageResponse,
    ToolUsageStats,
    UserCommand,
)
from ..services.database import get_connection, get_session_path, list_projects, list_sessions
from ..services.log_parser import (
    get_project_total_metrics,
    get_session_code_changes,
    get_session_errors,
    get_session_metrics,
    get_session_skills,
    get_session_subagents,
    get_session_tool_usage,
    parse_session_summary,
)
from ..services.queries import MESSAGES_PAGINATED_QUERY, USER_COMMANDS_QUERY

router = APIRouter(prefix="/api", tags=["sessions"])


def require_session_path(project_hash: str, session_id: str) -> Path:
    """Get session path and raise 404 if it doesn't exist."""
    session_path = get_session_path(project_hash, session_id)
    if not session_path.exists():
        raise HTTPException(status_code=404, detail="Session not found")
    return session_path


@router.get("/projects", response_model=ProjectListResponse)
async def get_projects() -> ProjectListResponse:
    """List all projects from ~/.claude/projects/."""
    projects_data = list_projects()
    projects = []

    for proj in projects_data:
        # Get aggregated metrics for each project
        metrics = get_project_total_metrics(proj["path_hash"])
        tokens_data = metrics.get("tokens", {})

        projects.append(
            ProjectResponse(
                path_hash=proj["path_hash"],
                project_path=proj["project_path"],
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

    # Sort by last activity, most recent first
    projects.sort(key=lambda p: p.last_activity or p.first_activity, reverse=True)

    return ProjectListResponse(projects=projects)


@router.get("/projects/{project_hash}/sessions", response_model=SessionListResponse)
async def get_project_sessions(project_hash: str) -> SessionListResponse:
    """List all sessions for a project."""
    sessions_data = list_sessions(project_hash)

    if not sessions_data:
        return SessionListResponse(sessions=[], total=0)

    sessions = []
    for sess in sessions_data:
        summary = parse_session_summary(project_hash, sess["session_id"])
        if summary:
            summary.slug = sess.get("slug")
            sessions.append(summary)

    # Sort by start time, most recent first
    sessions.sort(key=lambda s: s.start_time, reverse=True)

    return SessionListResponse(sessions=sessions, total=len(sessions))


@router.get("/projects/{project_hash}/metrics", response_model=SessionMetricsResponse)
async def get_project_metrics(project_hash: str) -> SessionMetricsResponse:
    """Get aggregated metrics for all sessions in a project."""
    sessions_data = list_sessions(project_hash)

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
        metrics = get_session_metrics(project_hash, sess["session_id"])
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
    """Get aggregated tool usage for all sessions in a project."""
    sessions_data = list_sessions(project_hash)

    if not sessions_data:
        return ToolUsageResponse(tools=[], total_calls=0)

    # Aggregate tool usage across all sessions
    tool_counts: dict[str, int] = {}

    for sess in sessions_data:
        tools_data = get_session_tool_usage(project_hash, sess["session_id"])
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
    """Get session details."""
    summary = parse_session_summary(project_hash, session_id)
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
) -> MessageListResponse:
    """Get paginated messages for a session."""
    session_path = require_session_path(project_hash, session_id)

    type_filter_sql = f"AND type = '{type_filter}'" if type_filter else ""
    offset = (page - 1) * per_page

    with get_connection() as conn:
        try:
            query = MESSAGES_PAGINATED_QUERY.format(
                path=str(session_path),
                sort_dir="ASC",
                type_filter=type_filter_sql,
                offset=offset,
                limit=per_page,
            )
            result = conn.execute(query).fetchall()

            count_query = f"""
            SELECT COUNT(*) FROM read_json_auto('{session_path}',
                maximum_object_size=104857600,
                ignore_errors=true
            )
            WHERE type IN ('assistant', 'user')
            {type_filter_sql}
            """
            total = conn.execute(count_query).fetchone()[0]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    messages = [_parse_message_row(row) for row in result]
    total_pages = (total + per_page - 1) // per_page

    return MessageListResponse(
        messages=messages,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


def _parse_message_row(row: tuple) -> MessageResponse:
    """Parse a database row into a MessageResponse."""
    msg_content = row[3]
    content_text = _extract_content_text(msg_content)

    tokens = TokenUsage()
    if row[5]:
        tokens = TokenUsage(
            input_tokens=row[5].get("input_tokens", 0),
            output_tokens=row[5].get("output_tokens", 0),
            cache_creation_input_tokens=row[5].get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=row[5].get("cache_read_input_tokens", 0),
        )

    return MessageResponse(
        uuid=row[0],
        type=row[1],
        timestamp=row[2],
        content=content_text[:500] if content_text else None,
        model=row[4],
        tokens=tokens,
        tools=[],
        has_tool_result=False,
        is_error=False,
        session_id=row[6],
    )


def _extract_content_text(msg_content: dict | None) -> str:
    """Extract text content from a message content object."""
    if not isinstance(msg_content, dict):
        return ""

    raw_content = msg_content.get("content")
    if isinstance(raw_content, str):
        return raw_content[:500]

    if isinstance(raw_content, list):
        text_parts = []
        for block in raw_content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", "")[:200])
            elif isinstance(block, str):
                text_parts.append(block[:200])
        return "".join(text_parts)

    return ""


@router.get("/sessions/{project_hash}/{session_id}/tools", response_model=ToolUsageResponse)
async def get_session_tools(project_hash: str, session_id: str) -> ToolUsageResponse:
    """Get tool usage statistics for a session."""
    require_session_path(project_hash, session_id)
    return get_session_tool_usage(project_hash, session_id)


@router.get("/sessions/{project_hash}/{session_id}/metrics", response_model=SessionMetricsResponse)
async def get_session_metrics_endpoint(
    project_hash: str, session_id: str
) -> SessionMetricsResponse:
    """Get detailed metrics for a session."""
    require_session_path(project_hash, session_id)
    return get_session_metrics(project_hash, session_id)


@router.get("/sessions/{project_hash}/{session_id}/subagents", response_model=SubagentListResponse)
async def get_session_subagents_endpoint(
    project_hash: str, session_id: str
) -> SubagentListResponse:
    """Get subagents spawned in a session."""
    require_session_path(project_hash, session_id)
    return get_session_subagents(project_hash, session_id)


@router.get("/sessions/{project_hash}/{session_id}/skills", response_model=SkillsResponse)
async def get_session_skills_endpoint(project_hash: str, session_id: str) -> SkillsResponse:
    """Get skills invoked in a session."""
    require_session_path(project_hash, session_id)
    return get_session_skills(project_hash, session_id)


@router.get(
    "/sessions/{project_hash}/{session_id}/code-changes", response_model=CodeChangesResponse
)
async def get_session_code_changes_endpoint(
    project_hash: str, session_id: str
) -> CodeChangesResponse:
    """Get code changes made in a session."""
    require_session_path(project_hash, session_id)
    return get_session_code_changes(project_hash, session_id)


@router.get("/sessions/{project_hash}/{session_id}/errors", response_model=ErrorsResponse)
async def get_session_errors_endpoint(project_hash: str, session_id: str) -> ErrorsResponse:
    """Get errors from a session."""
    require_session_path(project_hash, session_id)
    return get_session_errors(project_hash, session_id)


@router.get("/sessions/{project_hash}/{session_id}/commands", response_model=CommandsResponse)
async def get_session_commands(project_hash: str, session_id: str) -> CommandsResponse:
    """Get user commands with statistics for a session."""
    session_path = require_session_path(project_hash, session_id)

    with get_connection() as conn:
        try:
            result = conn.execute(USER_COMMANDS_QUERY.format(path=str(session_path))).fetchall()
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

"""Session-related API endpoints."""

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from ..models.entries import TokenUsage
from ..models.responses import (
    CodeChangesResponse,
    CommandsResponse,
    CommandsSummary,
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

        projects.append(
            ProjectResponse(
                path_hash=proj["path_hash"],
                project_path=proj["project_path"],
                session_count=metrics.get("session_count", proj.get("session_count", 0)),
                total_tokens=metrics.get("total_tokens", 0),
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

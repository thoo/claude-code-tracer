"""Subagent-related API endpoints."""

import json
from pathlib import Path

import orjson
from fastapi import APIRouter, HTTPException, Query

from ..models.entries import TokenUsage, ToolUse
from ..models.responses import (
    MessageDetailResponse,
    MessageListResponse,
    MessageResponse,
    SubagentResponse,
    ToolUsageResponse,
    ToolUsageStats,
)
from ..services.database import (
    get_connection,
    get_session_path,
    get_subagent_path,
    get_subagent_path_for_session,
)
from ..services.log_parser import _parse_timestamp
from ..services.queries import (
    MESSAGE_BY_INDEX_QUERY,
    MESSAGE_DETAIL_QUERY,
    MESSAGES_COMPREHENSIVE_QUERY,
    SESSION_TIMERANGE_QUERY,
    SUBAGENT_CALLS_WITH_AGENT_ID_QUERY,
    TOKEN_USAGE_QUERY,
    TOOL_USAGE_QUERY,
)

router = APIRouter(prefix="/api/subagents", tags=["subagents"])


def require_subagent_path(project_hash: str, agent_id: str) -> Path:
    """Get subagent path and raise 404 if it doesn't exist."""
    subagent_path = get_subagent_path(project_hash, agent_id)
    if not subagent_path.exists():
        raise HTTPException(status_code=404, detail="Subagent not found")
    return subagent_path


def _get_subagent_type(subagent_path: Path) -> str:
    """Extract subagent type from the first entry of the log file."""
    try:
        with open(subagent_path) as f:
            first_line = f.readline()
            if first_line:
                entry = json.loads(first_line)
                return entry.get("subagentType", "custom")
    except Exception:
        pass
    return "custom"


def _get_subagent_type_from_session(conn, session_path: Path, agent_id: str) -> str:
    """Get subagent type by querying the parent session's Task tool calls."""
    try:
        result = conn.execute(
            SUBAGENT_CALLS_WITH_AGENT_ID_QUERY.format(path=str(session_path))
        ).fetchall()
        for row in result:
            if row[0] == agent_id:
                return row[2] or "custom"  # subagent_type is at index 2
    except Exception:
        pass
    return "custom"


@router.get("/{project_hash}/{agent_id}", response_model=SubagentResponse)
async def get_subagent(project_hash: str, agent_id: str) -> SubagentResponse:
    """Get details for a specific subagent."""
    subagent_path = require_subagent_path(project_hash, agent_id)
    path = str(subagent_path)

    with get_connection() as conn:
        try:
            result = conn.execute(TOKEN_USAGE_QUERY.format(path=path)).fetchone()
            tokens = (
                TokenUsage(
                    input_tokens=result[0] or 0,
                    output_tokens=result[1] or 0,
                    cache_creation_input_tokens=result[2] or 0,
                    cache_read_input_tokens=result[3] or 0,
                )
                if result
                else TokenUsage()
            )
        except Exception:
            tokens = TokenUsage()

        try:
            rows = conn.execute(TOOL_USAGE_QUERY.format(path=path)).fetchall()
            tool_calls = sum(row[1] for row in rows)
        except Exception:
            tool_calls = 0

        try:
            result = conn.execute(SESSION_TIMERANGE_QUERY.format(path=path)).fetchone()
            start_time = _parse_timestamp(result[0]) if result else None
            end_time = _parse_timestamp(result[1]) if result else None
        except Exception:
            start_time = None
            end_time = None

    return SubagentResponse(
        agent_id=agent_id,
        subagent_type=_get_subagent_type(subagent_path),
        status="completed" if end_time else "running",
        start_time=start_time,
        end_time=end_time,
        tokens=tokens,
        tool_calls=tool_calls,
    )


@router.get("/{project_hash}/{agent_id}/tools", response_model=ToolUsageResponse)
async def get_subagent_tools(project_hash: str, agent_id: str) -> ToolUsageResponse:
    """Get tool usage for a subagent."""
    subagent_path = require_subagent_path(project_hash, agent_id)

    with get_connection() as conn:
        try:
            rows = conn.execute(TOOL_USAGE_QUERY.format(path=str(subagent_path))).fetchall()
        except Exception:
            return ToolUsageResponse()

        tools = [
            ToolUsageStats(
                name=row[0],
                count=row[1],
                avg_duration_seconds=row[2] or 0.0,
                error_count=row[3] or 0,
            )
            for row in rows
            if row[0]
        ]
        return ToolUsageResponse(tools=tools, total_calls=sum(t.count for t in tools))


def require_subagent_path_for_session(project_hash: str, session_id: str, agent_id: str) -> Path:
    """Get subagent path for a session and raise 404 if it doesn't exist."""
    subagent_path = get_subagent_path_for_session(project_hash, session_id, agent_id)
    if not subagent_path or not subagent_path.exists():
        raise HTTPException(status_code=404, detail="Subagent not found")
    return subagent_path


@router.get(
    "/{project_hash}/{session_id}/{agent_id}",
    response_model=SubagentResponse,
)
async def get_subagent_for_session(
    project_hash: str, session_id: str, agent_id: str
) -> SubagentResponse:
    """Get details for a specific subagent within a session context."""
    subagent_path = require_subagent_path_for_session(project_hash, session_id, agent_id)
    session_path = get_session_path(project_hash, session_id)
    path = str(subagent_path)

    with get_connection() as conn:
        # Get subagent type from parent session's Task tool call
        subagent_type = _get_subagent_type_from_session(conn, session_path, agent_id)

        try:
            result = conn.execute(TOKEN_USAGE_QUERY.format(path=path)).fetchone()
            tokens = (
                TokenUsage(
                    input_tokens=result[0] or 0,
                    output_tokens=result[1] or 0,
                    cache_creation_input_tokens=result[2] or 0,
                    cache_read_input_tokens=result[3] or 0,
                )
                if result
                else TokenUsage()
            )
        except Exception:
            tokens = TokenUsage()

        try:
            rows = conn.execute(TOOL_USAGE_QUERY.format(path=path)).fetchall()
            tool_calls = sum(row[1] for row in rows)
        except Exception:
            tool_calls = 0

        try:
            result = conn.execute(SESSION_TIMERANGE_QUERY.format(path=path)).fetchone()
            start_time = _parse_timestamp(result[0]) if result else None
            end_time = _parse_timestamp(result[1]) if result else None
        except Exception:
            start_time = None
            end_time = None

    return SubagentResponse(
        agent_id=agent_id,
        subagent_type=subagent_type,
        status="completed" if end_time else "running",
        start_time=start_time,
        end_time=end_time,
        tokens=tokens,
        tool_calls=tool_calls,
    )


@router.get(
    "/{project_hash}/{session_id}/{agent_id}/messages",
    response_model=MessageListResponse,
)
async def get_subagent_messages(
    project_hash: str,
    session_id: str,
    agent_id: str,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    type_filter: str | None = Query(default=None, alias="type"),
    error_only: bool = Query(default=False),
) -> MessageListResponse:
    """Get paginated messages for a subagent."""
    subagent_path = require_subagent_path_for_session(project_hash, session_id, agent_id)

    # Build WHERE clause for filtering
    where_conditions = []
    if type_filter:
        where_conditions.append(f"msg_type = '{type_filter}'")
    if error_only:
        where_conditions.append("is_error = true")

    where_clause = ""
    if where_conditions:
        where_clause = "WHERE " + " AND ".join(where_conditions)

    offset = (page - 1) * per_page

    with get_connection() as conn:
        try:
            # Get paginated messages using comprehensive query
            query = MESSAGES_COMPREHENSIVE_QUERY.format(
                path=str(subagent_path),
                sort_dir="ASC",
                where_clause=where_clause,
            )
            # Add pagination
            paginated_query = f"""
            WITH comprehensive AS ({query})
            SELECT * FROM comprehensive
            WHERE row_num > {offset}
            LIMIT {per_page}
            """
            result = conn.execute(paginated_query).fetchall()

            # Get total count for pagination
            count_query = f"""
            WITH comprehensive AS ({query})
            SELECT COUNT(*) FROM comprehensive
            """
            total = conn.execute(count_query).fetchone()[0]
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    messages = [_parse_comprehensive_message_row(row) for row in result]
    total_pages = (total + per_page - 1) // per_page

    return MessageListResponse(
        messages=messages,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@router.get(
    "/{project_hash}/{session_id}/{agent_id}/messages/{message_uuid}",
    response_model=MessageDetailResponse,
)
async def get_subagent_message_detail(
    project_hash: str,
    session_id: str,
    agent_id: str,
    message_uuid: str,
) -> MessageDetailResponse:
    """Get detailed information about a specific message in a subagent."""
    subagent_path = require_subagent_path_for_session(project_hash, session_id, agent_id)

    with get_connection() as conn:
        try:
            result = conn.execute(
                MESSAGE_DETAIL_QUERY.format(path=str(subagent_path), uuid=message_uuid)
            ).fetchone()

            if not result:
                raise HTTPException(status_code=404, detail="Message not found")

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    return _parse_message_detail_row(result)


@router.get(
    "/{project_hash}/{session_id}/{agent_id}/messages/by-index/{index}",
    response_model=MessageDetailResponse,
)
async def get_subagent_message_by_index(
    project_hash: str,
    session_id: str,
    agent_id: str,
    index: int,
) -> MessageDetailResponse:
    """Get message by its index (1-based) for prev/next navigation."""
    subagent_path = require_subagent_path_for_session(project_hash, session_id, agent_id)

    with get_connection() as conn:
        try:
            result = conn.execute(
                MESSAGE_BY_INDEX_QUERY.format(path=str(subagent_path), index=index)
            ).fetchone()

            if not result:
                raise HTTPException(status_code=404, detail="Message not found")

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e)) from e

    return _parse_message_detail_row(result)


def _parse_usage_data(usage_data: str | dict | None) -> TokenUsage:
    """Parse usage data into TokenUsage, handling both string and dict formats."""
    if not usage_data:
        return TokenUsage()

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


def _parse_comprehensive_message_row(row: tuple) -> MessageResponse:
    """Parse a comprehensive query row into a MessageResponse."""
    msg_type = row[1]

    if msg_type == "subagent":
        content_text = row[3] if row[3] else None
    else:
        content_text = _extract_content_text(row[3])

    if msg_type == "subagent":
        truncated_content = content_text
    else:
        truncated_content = content_text[:500] if content_text else None

    return MessageResponse(
        uuid=str(row[0]),
        type=msg_type,
        timestamp=row[2],
        content=truncated_content,
        model=row[4],
        tokens=_parse_usage_data(row[5]),
        tools=[],
        tool_names=row[7] or "",
        has_tool_result=msg_type == "tool_result",
        is_error=bool(row[8]),
        session_id=str(row[6]),
    )


def _extract_content_text(msg_content: dict | str | None) -> str:
    """Extract text content from a message content object."""
    if msg_content is None:
        return ""

    if isinstance(msg_content, str):
        original_str = msg_content
        try:
            msg_content = orjson.loads(msg_content)
        except (orjson.JSONDecodeError, ValueError):
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
                text_parts.append(block.get("text", "")[:200])
            elif block_type == "tool_result":
                result_content = block.get("content")
                if isinstance(result_content, str):
                    text_parts.append(result_content[:200])
            elif block_type == "tool_use":
                tool_name = block.get("name", "unknown")
                text_parts.append(f"[{tool_name}]")

        if text_parts:
            return " ".join(text_parts)

    return ""


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
    """Parse a message detail query row into MessageDetailResponse."""
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

"""Subagent-related API endpoints."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..models.entries import TokenUsage
from ..models.responses import SubagentResponse, ToolUsageResponse, ToolUsageStats
from ..services.database import get_connection, get_subagent_path
from ..services.log_parser import _parse_timestamp
from ..services.queries import SESSION_TIMERANGE_QUERY, TOKEN_USAGE_QUERY, TOOL_USAGE_QUERY

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
                return entry.get("subagentType", "unknown")
    except Exception:
        pass
    return "unknown"


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

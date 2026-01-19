"""Pydantic models for Claude Code log entries."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    """Token usage statistics from a message."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


class ToolUse(BaseModel):
    """Tool use block from assistant message."""

    type: str = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Tool result block from user message."""

    type: str = "tool_result"
    tool_use_id: str
    content: Any = None
    is_error: bool = False


class AssistantMessage(BaseModel):
    """Assistant message content."""

    role: str = "assistant"
    content: list[Any] = Field(default_factory=list)
    model: str | None = None
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: TokenUsage | None = None


class UserMessage(BaseModel):
    """User message content."""

    role: str = "user"
    content: Any = None


class BaseEntry(BaseModel):
    """Base log entry with common fields."""

    uuid: str
    parentUuid: str | None = None
    sessionId: str
    timestamp: datetime
    type: str
    cwd: str | None = None
    version: str | None = None
    gitBranch: str | None = None
    slug: str | None = None


class AssistantEntry(BaseEntry):
    """Assistant message entry."""

    type: str = "assistant"
    message: AssistantMessage
    isSidechain: bool = False


class UserEntry(BaseEntry):
    """User message entry."""

    type: str = "user"
    message: UserMessage
    toolUseResult: dict[str, Any] | None = None


class ProgressEntry(BaseEntry):
    """Progress update entry."""

    type: str = "progress"
    content: dict[str, Any] = Field(default_factory=dict)


class SummaryEntry(BaseEntry):
    """Summary entry for conversation."""

    type: str = "summary"
    summary: str
    leafUuid: str

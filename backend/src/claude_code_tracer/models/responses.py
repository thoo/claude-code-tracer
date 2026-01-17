"""Pydantic models for API responses."""

from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from .entries import TokenUsage, ToolUse


class CostBreakdown(BaseModel):
    """Cost breakdown by token type."""

    input_cost: float = 0.0
    output_cost: float = 0.0
    cache_creation_cost: float = 0.0
    cache_read_cost: float = 0.0

    @computed_field
    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost + self.cache_creation_cost + self.cache_read_cost


class ProjectResponse(BaseModel):
    """Project summary response."""

    path_hash: str
    project_path: str
    session_count: int = 0
    total_tokens: int = 0
    total_cost: float = 0.0
    last_activity: datetime | None = None
    first_activity: datetime | None = None


class ProjectListResponse(BaseModel):
    """List of projects response."""

    projects: list[ProjectResponse] = Field(default_factory=list)


class SessionSummary(BaseModel):
    """Session summary for listing."""

    session_id: str
    slug: str | None = None
    start_time: datetime
    end_time: datetime | None = None
    duration_seconds: int = 0
    message_count: int = 0
    tool_calls: int = 0
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    cost: float = 0.0
    errors: int = 0
    subagent_count: int = 0
    skills_used: list[str] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    """List of sessions response."""

    sessions: list[SessionSummary] = Field(default_factory=list)
    total: int = 0


class MessageResponse(BaseModel):
    """Single message response."""

    uuid: str
    type: str
    timestamp: datetime
    content: str | None = None
    model: str | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    tools: list[ToolUse] = Field(default_factory=list)
    has_tool_result: bool = False
    is_error: bool = False
    session_id: str


class MessageListResponse(BaseModel):
    """Paginated messages response."""

    messages: list[MessageResponse] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    per_page: int = 50
    total_pages: int = 0


class ToolUsageStats(BaseModel):
    """Tool usage statistics."""

    name: str
    count: int = 0
    avg_duration_seconds: float = 0.0
    error_count: int = 0


class ToolUsageResponse(BaseModel):
    """Tool usage response for a session."""

    tools: list[ToolUsageStats] = Field(default_factory=list)
    total_calls: int = 0


class SessionMetricsResponse(BaseModel):
    """Session metrics response."""

    tokens: TokenUsage = Field(default_factory=TokenUsage)
    cost: CostBreakdown = Field(default_factory=CostBreakdown)
    duration_seconds: int = 0
    message_count: int = 0
    tool_calls: int = 0
    error_count: int = 0
    cache_hit_rate: float = 0.0
    models_used: list[str] = Field(default_factory=list)
    interruption_rate: float = 0.0


class UserCommand(BaseModel):
    """User command with associated stats."""

    user_message: str
    timestamp: datetime
    assistant_steps: int = 0
    tools_used: int = 0
    tool_names: list[str] = Field(default_factory=list)
    estimated_tokens: int = 0
    followed_by_interruption: bool = False
    model: str | None = None


class CommandsSummary(BaseModel):
    """Summary statistics for commands."""

    total_commands: int = 0
    avg_steps_per_command: float = 0.0
    avg_tools_per_command: float = 0.0
    percentage_requiring_tools: float = 0.0
    interruption_rate: float = 0.0


class CommandsResponse(BaseModel):
    """User commands response."""

    commands: list[UserCommand] = Field(default_factory=list)
    summary: CommandsSummary = Field(default_factory=CommandsSummary)


class SubagentResponse(BaseModel):
    """Subagent information response."""

    agent_id: str
    subagent_type: str
    description: str | None = None
    status: str = "unknown"
    start_time: datetime | None = None
    end_time: datetime | None = None
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    tool_calls: int = 0


class SubagentListResponse(BaseModel):
    """List of subagents response."""

    subagents: list[SubagentResponse] = Field(default_factory=list)
    total_count: int = 0


class SkillUsage(BaseModel):
    """Skill usage information."""

    skill_name: str
    invocation_count: int = 0
    last_used: datetime | None = None


class SkillsResponse(BaseModel):
    """Skills usage response."""

    skills: list[SkillUsage] = Field(default_factory=list)
    total_invocations: int = 0


class FileChange(BaseModel):
    """Single file change information."""

    file_path: str
    operation: str  # "Edit" or "Write"
    lines_added: int = 0
    lines_removed: int = 0


class CodeChangesResponse(BaseModel):
    """Code changes response."""

    files_created: int = 0
    files_modified: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    net_lines: int = 0
    changes_by_file: list[FileChange] = Field(default_factory=list)


class DailyMetrics(BaseModel):
    """Daily aggregated metrics."""

    date: datetime
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    message_count: int = 0
    cost: float = 0.0


class DailyMetricsResponse(BaseModel):
    """Daily metrics response."""

    metrics: list[DailyMetrics] = Field(default_factory=list)


class ErrorEntry(BaseModel):
    """Error information."""

    timestamp: datetime
    tool_name: str | None = None
    error_message: str
    uuid: str


class ErrorsResponse(BaseModel):
    """Session errors response."""

    errors: list[ErrorEntry] = Field(default_factory=list)
    total: int = 0

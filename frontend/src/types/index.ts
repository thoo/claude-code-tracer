// Token usage statistics
export interface TokenUsage {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
}

// Cost breakdown
export interface CostBreakdown {
  input_cost: number;
  output_cost: number;
  cache_creation_cost: number;
  cache_read_cost: number;
  total_cost: number;
}

// Project types
export interface Project {
  path_hash: string;
  project_path: string;
  session_count: number;
  tokens: TokenUsage;
  total_tokens: number;
  total_cost: number;
  last_activity: string | null;
  first_activity: string | null;
}

export interface ProjectListResponse {
  projects: Project[];
}

// Session types
export type SessionStatus = 'running' | 'idle' | 'completed' | 'interrupted' | 'unknown';

export interface SessionSummary {
  session_id: string;
  slug: string | null;
  status: SessionStatus;
  start_time: string;
  end_time: string | null;
  duration_seconds: number;
  message_count: number;
  tool_calls: number;
  tokens: TokenUsage;
  cost: number;
  errors: number;
  subagent_count: number;
  skills_used: string[];
}

export interface SessionListResponse {
  sessions: SessionSummary[];
  total: number;
}

// Message types
export interface ToolUse {
  type: string;
  id: string;
  name: string;
  input: Record<string, unknown>;
}

export interface Message {
  uuid: string;
  type: string;
  timestamp: string;
  content: string | null;
  model: string | null;
  tokens: TokenUsage;
  tools: ToolUse[];
  tool_names: string;
  has_tool_result: boolean;
  is_error: boolean;
  session_id: string;
}

export interface MessageListResponse {
  messages: Message[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

// Tool usage types
export interface ToolUsageStats {
  name: string;
  count: number;
  avg_duration_seconds: number;
  error_count: number;
}

export interface ToolUsageResponse {
  tools: ToolUsageStats[];
  total_calls: number;
}

// Session metrics
export interface SessionMetrics {
  tokens: TokenUsage;
  cost: CostBreakdown;
  duration_seconds: number;
  message_count: number;
  tool_calls: number;
  error_count: number;
  cache_hit_rate: number;
  models_used: string[];
  interruption_rate: number;
}

// Commands types
export interface UserCommand {
  user_message: string;
  timestamp: string;
  assistant_steps: number;
  tools_used: number;
  tool_names: string[];
  estimated_tokens: number;
  followed_by_interruption: boolean;
  model: string | null;
}

export interface CommandsSummary {
  total_commands: number;
  avg_steps_per_command: number;
  avg_tools_per_command: number;
  percentage_requiring_tools: number;
  interruption_rate: number;
}

export interface CommandsResponse {
  commands: UserCommand[];
  summary: CommandsSummary;
}

// Subagent types
export interface Subagent {
  agent_id: string;
  subagent_type: string;
  description: string | null;
  status: string;
  start_time: string | null;
  end_time: string | null;
  tokens: TokenUsage;
  tool_calls: number;
}

export interface SubagentListResponse {
  subagents: Subagent[];
  total_count: number;
}

// Skills types
export interface SkillUsage {
  skill_name: string;
  invocation_count: number;
  last_used: string | null;
}

export interface SkillsResponse {
  skills: SkillUsage[];
  total_invocations: number;
}

// Code changes types
export interface FileChange {
  file_path: string;
  operation: string;
  lines_added: number;
  lines_removed: number;
}

export interface CodeChangesResponse {
  files_created: number;
  files_modified: number;
  lines_added: number;
  lines_removed: number;
  net_lines: number;
  changes_by_file: FileChange[];
}

// Daily metrics
export interface DailyMetrics {
  date: string;
  input_tokens: number;
  output_tokens: number;
  cache_creation: number;
  cache_read: number;
  message_count: number;
  cost: number;
}

export interface DailyMetricsResponse {
  metrics: DailyMetrics[];
}

// Errors types
export interface ErrorEntry {
  timestamp: string;
  tool_name: string | null;
  error_message: string;
  uuid: string;
}

export interface ErrorsResponse {
  errors: ErrorEntry[];
  total: number;
}

// Message filter types
export interface ToolFilterOption {
  name: string;
  count: number;
}

export interface MessageFilterOptions {
  types: string[];
  tools: ToolFilterOption[];
  error_count: number;
}

// Message detail types
export interface MessageDetailResponse {
  uuid: string;
  message_id: string | null;
  type: string;
  timestamp: string;
  content: string | null;
  model: string | null;
  tokens: TokenUsage;
  tools: ToolUse[];
  tool_results: ToolResult[];
  is_error: boolean;
  session_id: string;
  cwd: string | null;
  message_index: number;
  total_messages: number;
}

export interface ToolResult {
  type: string;
  tool_use_id: string;
  content: unknown;
  is_error?: boolean;
}

// Pricing types
export interface ModelPricing {
  input: number;
  output: number;
  cache_create: number;
  cache_read: number;
}

export interface PricingResponse {
  pricing: Record<string, ModelPricing>;
}

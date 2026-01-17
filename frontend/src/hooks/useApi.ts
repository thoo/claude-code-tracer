import { useQuery } from '@tanstack/react-query';
import { fetchApi, buildQueryString } from '../lib/api';
import type {
  ProjectListResponse,
  SessionListResponse,
  SessionSummary,
  SessionMetrics,
  MessageListResponse,
  MessageFilterOptions,
  MessageDetailResponse,
  ToolUsageResponse,
  CommandsResponse,
  SubagentListResponse,
  SkillsResponse,
  CodeChangesResponse,
  ErrorsResponse,
  DailyMetricsResponse,
  PricingResponse,
} from '../types';

// Projects
export function useProjects() {
  return useQuery({
    queryKey: ['projects'],
    queryFn: () => fetchApi<ProjectListResponse>('/projects'),
  });
}

// Sessions
export function useProjectSessions(projectHash: string) {
  return useQuery({
    queryKey: ['sessions', projectHash],
    queryFn: () => fetchApi<SessionListResponse>(`/projects/${projectHash}/sessions`),
    enabled: !!projectHash,
  });
}

export function useSession(projectHash: string, sessionId: string) {
  return useQuery({
    queryKey: ['session', projectHash, sessionId],
    queryFn: () => fetchApi<SessionSummary>(`/sessions/${projectHash}/${sessionId}`),
    enabled: !!projectHash && !!sessionId,
  });
}

// Messages
export function useSessionMessages(
  projectHash: string,
  sessionId: string,
  options: {
    page?: number;
    perPage?: number;
    type?: string;
    tool?: string;
    errorOnly?: boolean;
    search?: string;
  } = {}
) {
  const { page = 1, perPage = 50, type, tool, errorOnly, search } = options;

  return useQuery({
    queryKey: ['messages', projectHash, sessionId, page, perPage, type, tool, errorOnly, search],
    queryFn: () =>
      fetchApi<MessageListResponse>(
        `/sessions/${projectHash}/${sessionId}/messages${buildQueryString({
          page,
          per_page: perPage,
          type,
          tool,
          error_only: errorOnly,
          search,
        })}`
      ),
    enabled: !!projectHash && !!sessionId,
  });
}

// Message filter options
export function useSessionMessageFilters(projectHash: string, sessionId: string) {
  return useQuery({
    queryKey: ['message-filters', projectHash, sessionId],
    queryFn: () => fetchApi<MessageFilterOptions>(`/sessions/${projectHash}/${sessionId}/messages/filters`),
    enabled: !!projectHash && !!sessionId,
  });
}

// Message detail
export function useMessageDetail(projectHash: string, sessionId: string, messageUuid: string) {
  return useQuery({
    queryKey: ['message-detail', projectHash, sessionId, messageUuid],
    queryFn: () => fetchApi<MessageDetailResponse>(`/sessions/${projectHash}/${sessionId}/messages/${messageUuid}`),
    enabled: !!projectHash && !!sessionId && !!messageUuid,
  });
}

// Message by index (for navigation)
export function useMessageByIndex(projectHash: string, sessionId: string, index: number) {
  return useQuery({
    queryKey: ['message-by-index', projectHash, sessionId, index],
    queryFn: () => fetchApi<MessageDetailResponse>(`/sessions/${projectHash}/${sessionId}/messages/by-index/${index}`),
    enabled: !!projectHash && !!sessionId && index > 0,
  });
}

// Metrics
export function useSessionMetrics(projectHash: string, sessionId: string) {
  return useQuery({
    queryKey: ['metrics', projectHash, sessionId],
    queryFn: () => fetchApi<SessionMetrics>(`/sessions/${projectHash}/${sessionId}/metrics`),
    enabled: !!projectHash && !!sessionId,
  });
}

// Project-level metrics (aggregated across all sessions)
export function useProjectMetrics(projectHash: string) {
  return useQuery({
    queryKey: ['project-metrics', projectHash],
    queryFn: () => fetchApi<SessionMetrics>(`/projects/${projectHash}/metrics`),
    enabled: !!projectHash,
  });
}

// Tools
export function useSessionTools(projectHash: string, sessionId: string) {
  return useQuery({
    queryKey: ['tools', projectHash, sessionId],
    queryFn: () => fetchApi<ToolUsageResponse>(`/sessions/${projectHash}/${sessionId}/tools`),
    enabled: !!projectHash && !!sessionId,
  });
}

// Project-level tools (aggregated across all sessions)
export function useProjectTools(projectHash: string) {
  return useQuery({
    queryKey: ['project-tools', projectHash],
    queryFn: () => fetchApi<ToolUsageResponse>(`/projects/${projectHash}/tools`),
    enabled: !!projectHash,
  });
}

// Commands
export function useSessionCommands(projectHash: string, sessionId: string) {
  return useQuery({
    queryKey: ['commands', projectHash, sessionId],
    queryFn: () => fetchApi<CommandsResponse>(`/sessions/${projectHash}/${sessionId}/commands`),
    enabled: !!projectHash && !!sessionId,
  });
}

// Subagents
export function useSessionSubagents(projectHash: string, sessionId: string) {
  return useQuery({
    queryKey: ['subagents', projectHash, sessionId],
    queryFn: () => fetchApi<SubagentListResponse>(`/sessions/${projectHash}/${sessionId}/subagents`),
    enabled: !!projectHash && !!sessionId,
  });
}

export function useSubagentDetail(projectHash: string, agentId: string) {
  return useQuery({
    queryKey: ['subagent', projectHash, agentId],
    queryFn: () => fetchApi<{
      agent_id: string;
      subagent_type: string;
      description: string | null;
      status: string;
      start_time: string | null;
      end_time: string | null;
      tokens: {
        input_tokens: number;
        output_tokens: number;
        cache_creation_input_tokens: number;
        cache_read_input_tokens: number;
      };
      tool_calls: number;
    }>(`/subagents/${projectHash}/${agentId}`),
    enabled: !!projectHash && !!agentId,
  });
}

// Skills
export function useSessionSkills(projectHash: string, sessionId: string) {
  return useQuery({
    queryKey: ['skills', projectHash, sessionId],
    queryFn: () => fetchApi<SkillsResponse>(`/sessions/${projectHash}/${sessionId}/skills`),
    enabled: !!projectHash && !!sessionId,
  });
}

// Code changes
export function useSessionCodeChanges(projectHash: string, sessionId: string) {
  return useQuery({
    queryKey: ['code-changes', projectHash, sessionId],
    queryFn: () => fetchApi<CodeChangesResponse>(`/sessions/${projectHash}/${sessionId}/code-changes`),
    enabled: !!projectHash && !!sessionId,
  });
}

// Errors
export function useSessionErrors(projectHash: string, sessionId: string) {
  return useQuery({
    queryKey: ['errors', projectHash, sessionId],
    queryFn: () => fetchApi<ErrorsResponse>(`/sessions/${projectHash}/${sessionId}/errors`),
    enabled: !!projectHash && !!sessionId,
  });
}

// Daily metrics (for charts)
export function useDailyMetrics(
  projectHash: string,
  options: {
    startDate?: string;
    endDate?: string;
  } = {}
) {
  return useQuery({
    queryKey: ['daily-metrics', projectHash, options.startDate, options.endDate],
    queryFn: () =>
      fetchApi<DailyMetricsResponse>(
        `/metrics/daily/${projectHash}${buildQueryString({
          start_date: options.startDate,
          end_date: options.endDate,
        })}`
      ),
    enabled: !!projectHash,
  });
}

// Pricing
export function usePricing() {
  return useQuery({
    queryKey: ['pricing'],
    queryFn: () => fetchApi<PricingResponse>('/pricing'),
    staleTime: 1000 * 60 * 60, // 1 hour
  });
}

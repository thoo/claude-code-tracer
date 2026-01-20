import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import clsx from 'clsx';
import { useProjectSessions, useProjectMetrics, useProjectTools } from '../hooks/useApi';
import {
  formatCost,
  formatTokens,
  formatDuration,
  formatDateTime,
  formatRelativeTime,
  getTotalTokens,
} from '../lib/formatting';
import LoadingSpinner from '../components/common/LoadingSpinner';
import ErrorDisplay from '../components/common/ErrorDisplay';
import EmptyState from '../components/common/EmptyState';
import StatsCard from '../components/common/StatsCard';
import Badge from '../components/common/Badge';
import ToolUsageChart from '../components/charts/ToolUsageChart';
import type { SessionSummary, SessionStatus } from '../types';

type TabType = 'sessions' | 'metrics';

export default function ProjectDashboard() {
  const { projectHash } = useParams<{ projectHash: string }>();
  const [activeTab, setActiveTab] = useState<TabType>('sessions');

  const { data: sessionsData, isLoading, error, refetch } = useProjectSessions(projectHash || '');

  if (isLoading) {
    return (
      <div className="py-20">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (error) {
    return (
      <ErrorDisplay
        message={error instanceof Error ? error.message : 'Failed to load sessions'}
        onRetry={() => refetch()}
      />
    );
  }

  const sessions = (sessionsData?.sessions || []).filter(s => s.message_count > 0);

  if (sessions.length === 0) {
    return (
      <div>
        <Breadcrumb projectHash={projectHash || ''} />
        <EmptyState
          icon={
            <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
          }
          title="No sessions found"
          description="This project doesn't have any Claude Code sessions yet."
        />
      </div>
    );
  }

  // Calculate project-wide stats
  const projectStats = calculateProjectStats(sessions);

  return (
    <div className="space-y-6">
      <Breadcrumb projectHash={projectHash || ''} />

      {/* Project stats */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Sessions"
          value={projectStats.totalSessions}
          variant="accent"
          subtitle={`${projectStats.avgMessagesPerSession.toFixed(1)} avg messages/session`}
        />
        <StatsCard
          title="Total Tokens"
          value={formatTokens(projectStats.totalTokens)}
          breakdown={[
            { label: 'Input', value: formatTokens(projectStats.inputTokens) },
            { label: 'Output', value: formatTokens(projectStats.outputTokens) },
            { label: 'Cache Create', value: formatTokens(projectStats.cacheCreationTokens) },
            { label: 'Cache Read', value: formatTokens(projectStats.cacheReadTokens) },
          ]}
        />
        <StatsCard
          title="Total Cost"
          value={formatCost(projectStats.totalCost)}
          variant="highlight"
          subtitle={`${formatCost(projectStats.avgCostPerSession)} avg/session`}
        />
        <StatsCard
          title="Tool Calls"
          value={projectStats.totalToolCalls}
          subtitle={`${projectStats.avgToolsPerSession.toFixed(1)} avg/session`}
        />
      </div>

      {/* Tabs */}
      <div className="tab-list">
        {(['sessions', 'metrics'] as const).map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={clsx(
              'tab capitalize',
              activeTab === tab && 'tab-active'
            )}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'sessions' && (
        <SessionsList sessions={sessions} projectHash={projectHash || ''} />
      )}

      {activeTab === 'metrics' && (
        <ProjectMetricsView projectHash={projectHash || ''} />
      )}
    </div>
  );
}

interface BreadcrumbProps {
  projectHash: string;
}

function Breadcrumb({ projectHash }: BreadcrumbProps) {
  return (
    <nav className="flex items-center gap-2 text-base text-gray-500 dark:text-surface-400">
      <Link to="/" className="hover:text-gray-700 dark:hover:text-surface-300 transition-colors">
        Projects
      </Link>
      <svg className="h-4 w-4 text-gray-400 dark:text-surface-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
      </svg>
      <span className="font-medium text-gray-700 dark:text-surface-200 truncate max-w-xs font-mono">{projectHash}</span>
    </nav>
  );
}

interface SessionsListProps {
  sessions: SessionSummary[];
  projectHash: string;
}

function SessionsList({ sessions, projectHash }: SessionsListProps) {
  return (
    <div className="table-container">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="table-header">
            <tr>
              <th>Session</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Messages</th>
              <th>Tool Calls</th>
              <th>Tokens</th>
              <th>Cache Hit</th>
              <th>Cost</th>
              <th>Errors</th>
            </tr>
          </thead>
          <tbody>
            {sessions.map((session, index) => (
              <SessionRow key={session.session_id} session={session} projectHash={projectHash} index={index} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface SessionRowProps {
  session: SessionSummary;
  projectHash: string;
  index: number;
}

function SessionRow({ session, projectHash, index }: SessionRowProps) {
  // Calculate cache hit rate
  const totalCacheTokens = session.tokens.cache_creation_input_tokens + session.tokens.cache_read_input_tokens;
  const totalInputTokens = session.tokens.input_tokens + totalCacheTokens;
  const cacheHitRate = totalInputTokens > 0
    ? (session.tokens.cache_read_input_tokens / totalInputTokens * 100)
    : 0;

  return (
    <tr
      className="table-row animate-fade-in"
      style={{ animationDelay: `${index * 0.03}s` }}
    >
      <td>
        <Link to={`/session/${projectHash}/${session.session_id}`} className="block group">
          <div className="font-medium text-gray-900 dark:text-surface-100 group-hover:text-accent-600 dark:group-hover:text-accent-400 transition-colors">
            {session.slug || session.session_id}
          </div>
          <div className="text-sm text-gray-500 dark:text-surface-400 font-mono" title={formatDateTime(session.start_time)}>
            {formatRelativeTime(session.start_time)}
          </div>
        </Link>
      </td>
      <td>
        <SessionStatusBadge status={session.status} />
      </td>
      <td className="font-mono">{formatDuration(session.duration_seconds)}</td>
      <td className="font-mono">{session.message_count}</td>
      <td className="font-mono">{session.tool_calls}</td>
      <td>
        <div className="font-mono">{formatTokens(getTotalTokens(session.tokens))}</div>
        <div className="text-sm text-gray-500 dark:text-surface-400 font-mono">
          {formatTokens(session.tokens.cache_read_input_tokens)} cached
        </div>
      </td>
      <td className="font-mono">{cacheHitRate.toFixed(1)}%</td>
      <td className="font-mono text-gray-700 dark:text-surface-200">{formatCost(session.cost)}</td>
      <td>
        {session.errors > 0 ? (
          <Badge variant="error">{session.errors}</Badge>
        ) : (
          <Badge variant="success">0</Badge>
        )}
      </td>
    </tr>
  );
}

interface ProjectMetricsViewProps {
  projectHash: string;
}

function ProjectMetricsView({ projectHash }: ProjectMetricsViewProps) {
  const { data: metrics, isLoading: metricsLoading } = useProjectMetrics(projectHash);
  const { data: toolsData, isLoading: toolsLoading } = useProjectTools(projectHash);

  if (metricsLoading || toolsLoading) {
    return <LoadingSpinner />;
  }

  return (
    <div className="space-y-6">
      {/* Metrics cards */}
      {metrics && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <StatsCard
            title="Cache Hit Rate"
            value={`${metrics.cache_hit_rate.toFixed(1)}%`}
            subtitle="Cache efficiency"
          />
          <StatsCard
            title="Interruption Rate"
            value={`${metrics.interruption_rate.toFixed(1)}%`}
            subtitle="Commands interrupted"
          />
          <StatsCard
            title="Total Cost"
            value={formatCost(metrics.cost.total_cost)}
            variant="accent"
            breakdown={[
              { label: 'Input', value: formatCost(metrics.cost.input_cost) },
              { label: 'Output', value: formatCost(metrics.cost.output_cost) },
              { label: 'Cache Creation', value: formatCost(metrics.cost.cache_creation_cost) },
              { label: 'Cache Read', value: formatCost(metrics.cost.cache_read_cost) },
            ]}
          />
          <StatsCard
            title="Models Used"
            value={metrics.models_used.length}
            subtitle={metrics.models_used.join(', ')}
          />
        </div>
      )}

      {/* Tool usage chart */}
      {toolsData && toolsData.tools.length > 0 && (
        <div className="chart-container">
          <h3 className="mb-4 text-xl font-semibold text-gray-900 dark:text-surface-100">Tool Usage</h3>
          <ToolUsageChart tools={toolsData.tools} />
        </div>
      )}
    </div>
  );
}

function SessionStatusBadge({ status }: { status: SessionStatus }) {
  const config: Record<SessionStatus, { label: string; variant: 'success' | 'warning' | 'gray' | 'error' | 'primary' }> = {
    running: { label: 'Running', variant: 'success' },
    idle: { label: 'Idle', variant: 'warning' },
    completed: { label: 'Completed', variant: 'gray' },
    interrupted: { label: 'Interrupted', variant: 'error' },
    unknown: { label: 'Unknown', variant: 'gray' },
  };

  const { label, variant } = config[status] || config.unknown;

  return (
    <span className={clsx('badge', `badge-${variant}`)}>
      {status === 'running' && (
        <span className="relative flex h-2 w-2 mr-1">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-success-400 opacity-75" />
          <span className="relative inline-flex rounded-full h-2 w-2 bg-success-500" />
        </span>
      )}
      {label}
    </span>
  );
}

function calculateProjectStats(sessions: SessionSummary[]) {
  const totalSessions = sessions.length;
  const totalTokens = sessions.reduce((sum, s) => sum + getTotalTokens(s.tokens), 0);
  const inputTokens = sessions.reduce((sum, s) => sum + s.tokens.input_tokens, 0);
  const outputTokens = sessions.reduce((sum, s) => sum + s.tokens.output_tokens, 0);
  const cacheCreationTokens = sessions.reduce((sum, s) => sum + s.tokens.cache_creation_input_tokens, 0);
  const cacheReadTokens = sessions.reduce((sum, s) => sum + s.tokens.cache_read_input_tokens, 0);
  const totalCost = sessions.reduce((sum, s) => sum + s.cost, 0);
  const totalToolCalls = sessions.reduce((sum, s) => sum + s.tool_calls, 0);
  const totalMessages = sessions.reduce((sum, s) => sum + s.message_count, 0);

  return {
    totalSessions,
    totalTokens,
    inputTokens,
    outputTokens,
    cacheCreationTokens,
    cacheReadTokens,
    totalCost,
    totalToolCalls,
    avgCostPerSession: totalSessions > 0 ? totalCost / totalSessions : 0,
    avgToolsPerSession: totalSessions > 0 ? totalToolCalls / totalSessions : 0,
    avgMessagesPerSession: totalSessions > 0 ? totalMessages / totalSessions : 0,
  };
}

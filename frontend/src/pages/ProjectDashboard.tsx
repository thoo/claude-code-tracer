import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
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

  const sessions = sessionsData?.sessions || [];

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
          subtitle={`${formatCost(projectStats.avgCostPerSession)} avg/session`}
        />
        <StatsCard
          title="Tool Calls"
          value={projectStats.totalToolCalls}
          subtitle={`${projectStats.avgToolsPerSession.toFixed(1)} avg/session`}
        />
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-4">
          {(['sessions', 'metrics'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`border-b-2 pb-3 text-sm font-medium capitalize transition-colors ${
                activeTab === tab
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              }`}
            >
              {tab}
            </button>
          ))}
        </nav>
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
    <nav className="flex items-center gap-2 text-sm text-gray-500">
      <Link to="/" className="hover:text-gray-700">
        Projects
      </Link>
      <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
      </svg>
      <span className="font-medium text-gray-900 truncate max-w-xs">{projectHash}</span>
    </nav>
  );
}

interface SessionsListProps {
  sessions: SessionSummary[];
  projectHash: string;
}

function SessionsList({ sessions, projectHash }: SessionsListProps) {
  return (
    <div className="card overflow-hidden !p-0">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50/50">
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Session
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Status
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Duration
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Messages
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Tool Calls
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Tokens
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Cache Hit
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Cost
              </th>
              <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                Errors
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {sessions.map((session) => (
              <SessionRow key={session.session_id} session={session} projectHash={projectHash} />
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
}

function SessionRow({ session, projectHash }: SessionRowProps) {
  // Calculate cache hit rate
  const totalCacheTokens = session.tokens.cache_creation_input_tokens + session.tokens.cache_read_input_tokens;
  const totalInputTokens = session.tokens.input_tokens + totalCacheTokens;
  const cacheHitRate = totalInputTokens > 0
    ? (session.tokens.cache_read_input_tokens / totalInputTokens * 100)
    : 0;

  return (
    <tr className="transition-colors hover:bg-gray-50/50">
      <td className="px-6 py-4">
        <Link to={`/session/${projectHash}/${session.session_id}`} className="block group">
          <div className="font-medium text-gray-900 group-hover:text-primary-600">
            {session.slug || session.session_id}
          </div>
          <div className="text-sm text-gray-500" title={formatDateTime(session.start_time)}>
            {formatRelativeTime(session.start_time)}
          </div>
        </Link>
      </td>
      <td className="px-6 py-4">
        <SessionStatusBadge status={session.status} />
      </td>
      <td className="px-6 py-4 text-sm text-gray-700">{formatDuration(session.duration_seconds)}</td>
      <td className="px-6 py-4 text-sm text-gray-700">{session.message_count}</td>
      <td className="px-6 py-4 text-sm text-gray-700">{session.tool_calls}</td>
      <td className="px-6 py-4 text-sm text-gray-700">
        <div>{formatTokens(getTotalTokens(session.tokens))}</div>
        <div className="text-xs text-gray-400">
          {formatTokens(session.tokens.cache_creation_input_tokens)} create · {formatTokens(session.tokens.cache_read_input_tokens)} read
        </div>
      </td>
      <td className="px-6 py-4 text-sm text-gray-700">{cacheHitRate.toFixed(1)}%</td>
      <td className="px-6 py-4 text-sm text-gray-700">{formatCost(session.cost)}</td>
      <td className="px-6 py-4">
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
        <div className="card">
          <h3 className="mb-4 text-lg font-semibold text-gray-900">Tool Usage</h3>
          <ToolUsageChart tools={toolsData.tools} />
        </div>
      )}
    </div>
  );
}

function SessionStatusBadge({ status }: { status: SessionStatus }) {
  const config: Record<SessionStatus, { label: string; className: string }> = {
    running: {
      label: 'Running',
      className: 'bg-green-100 text-green-800 border-green-200',
    },
    idle: {
      label: 'Idle',
      className: 'bg-yellow-100 text-yellow-800 border-yellow-200',
    },
    completed: {
      label: 'Completed',
      className: 'bg-gray-100 text-gray-600 border-gray-200',
    },
    interrupted: {
      label: 'Interrupted',
      className: 'bg-orange-100 text-orange-800 border-orange-200',
    },
    unknown: {
      label: 'Unknown',
      className: 'bg-gray-100 text-gray-500 border-gray-200',
    },
  };

  const { label, className } = config[status] || config.unknown;

  return (
    <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 text-xs font-medium rounded-full border ${className}`}>
      {status === 'running' && (
        <span className="relative flex h-2 w-2">
          <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
          <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
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

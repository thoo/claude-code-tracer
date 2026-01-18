import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  useSubagentInfo,
  useSubagentMessages,
  useSubagentTools,
} from '../hooks/useApi';
import {
  formatTokens,
  formatDuration,
  formatDateTime,
  getTotalTokens,
  truncateText,
} from '../lib/formatting';
import LoadingSpinner from '../components/common/LoadingSpinner';
import ErrorDisplay from '../components/common/ErrorDisplay';
import StatsCard from '../components/common/StatsCard';
import Badge from '../components/common/Badge';
import Pagination from '../components/common/Pagination';
import ToolUsageChart from '../components/charts/ToolUsageChart';
import MessageDetailModal from '../components/MessageDetailModal';

type TabType = 'messages' | 'tools';

export default function SubagentDetail() {
  const { projectHash, sessionId, agentId } = useParams<{
    projectHash: string;
    sessionId: string;
    agentId: string;
  }>();
  const [activeTab, setActiveTab] = useState<TabType>('messages');
  const [messagePage, setMessagePage] = useState(1);

  const { data: subagent, isLoading, error, refetch } = useSubagentInfo(
    projectHash || '',
    sessionId || '',
    agentId || ''
  );

  if (isLoading) {
    return (
      <div className="py-20">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (error || !subagent) {
    return (
      <ErrorDisplay
        message={error instanceof Error ? error.message : 'Failed to load subagent'}
        onRetry={() => refetch()}
      />
    );
  }

  const duration = subagent.start_time && subagent.end_time
    ? Math.round((new Date(subagent.end_time).getTime() - new Date(subagent.start_time).getTime()) / 1000)
    : 0;

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-2 text-sm text-gray-500">
        <Link to="/" className="hover:text-gray-700">Projects</Link>
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <Link to={`/project/${projectHash}`} className="hover:text-gray-700 truncate max-w-[120px]">
          {projectHash}
        </Link>
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <Link to={`/session/${projectHash}/${sessionId}`} className="hover:text-gray-700 truncate max-w-[120px]">
          Session
        </Link>
        <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <span className="font-medium text-gray-900">Subagent {agentId}</span>
      </nav>

      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
            Subagent
            <Badge variant="primary">{subagent.subagent_type}</Badge>
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Agent ID: <span className="font-mono">{agentId}</span>
            {subagent.description && <span className="ml-3">{subagent.description}</span>}
          </p>
          {subagent.start_time && (
            <p className="mt-1 text-sm text-gray-500">
              Started {formatDateTime(subagent.start_time)}
              {subagent.end_time && ` - Ended ${formatDateTime(subagent.end_time)}`}
            </p>
          )}
        </div>
        <Badge variant={subagent.status === 'completed' ? 'success' : subagent.status === 'running' ? 'primary' : 'gray'}>
          {subagent.status}
        </Badge>
      </div>

      {/* Stats cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Duration"
          value={formatDuration(duration)}
        />
        <StatsCard
          title="Tool Calls"
          value={subagent.tool_calls}
        />
        <StatsCard
          title="Tokens"
          value={formatTokens(getTotalTokens(subagent.tokens))}
          breakdown={[
            { label: 'Input', value: formatTokens(subagent.tokens.input_tokens) },
            { label: 'Output', value: formatTokens(subagent.tokens.output_tokens) },
          ]}
        />
        <StatsCard
          title="Status"
          value={subagent.status}
          subtitle={subagent.end_time ? 'Completed' : 'In progress'}
        />
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-4 overflow-x-auto">
          {(['messages', 'tools'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`whitespace-nowrap border-b-2 pb-3 text-sm font-medium capitalize transition-colors ${
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
      {activeTab === 'messages' && (
        <MessagesTab
          projectHash={projectHash || ''}
          sessionId={sessionId || ''}
          agentId={agentId || ''}
          page={messagePage}
          onPageChange={setMessagePage}
        />
      )}
      {activeTab === 'tools' && (
        <ToolsTab
          projectHash={projectHash || ''}
          sessionId={sessionId || ''}
          agentId={agentId || ''}
        />
      )}
    </div>
  );
}

interface TabProps {
  projectHash: string;
  sessionId: string;
  agentId: string;
}

function MessagesTab({
  projectHash,
  sessionId,
  agentId,
  page,
  onPageChange,
}: TabProps & { page: number; onPageChange: (p: number) => void }) {
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [errorOnly, setErrorOnly] = useState(false);
  const [selectedMessageUuid, setSelectedMessageUuid] = useState<string | null>(null);

  const { data, isLoading } = useSubagentMessages(projectHash, sessionId, agentId, {
    page,
    perPage: 20,
    type: typeFilter || undefined,
    errorOnly: errorOnly || undefined,
  });

  const messages = data?.messages || [];

  return (
    <div className="space-y-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-4">
        {/* Type filter */}
        <div className="flex items-center gap-2">
          <label htmlFor="type-filter" className="text-sm font-medium text-gray-700">
            Type:
          </label>
          <select
            id="type-filter"
            value={typeFilter}
            onChange={(e) => {
              setTypeFilter(e.target.value);
              onPageChange(1);
            }}
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          >
            <option value="">All types</option>
            <option value="assistant">assistant</option>
            <option value="user">user</option>
            <option value="tool_result">tool_result</option>
          </select>
        </div>

        {/* Error only toggle */}
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={errorOnly}
            onChange={(e) => {
              setErrorOnly(e.target.checked);
              onPageChange(1);
            }}
            className="h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
          />
          <span className="text-sm font-medium text-gray-700">Errors only</span>
        </label>

        {/* Clear filters */}
        {(typeFilter || errorOnly) && (
          <button
            onClick={() => {
              setTypeFilter('');
              setErrorOnly(false);
              onPageChange(1);
            }}
            className="text-sm text-gray-500 hover:text-gray-700 underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {isLoading ? (
        <LoadingSpinner />
      ) : messages.length === 0 ? (
        <div className="card text-center text-gray-500 py-8">
          No messages found{(typeFilter || errorOnly) ? ' matching filters' : ''}
        </div>
      ) : (
        <>
          <div className="card overflow-hidden !p-0">
            <div className="divide-y divide-gray-100">
              {messages.map((msg) => (
                <div
                  key={msg.uuid}
                  className={`px-6 py-4 cursor-pointer transition-colors hover:bg-gray-50 ${msg.is_error ? 'bg-red-50 hover:bg-red-100' : ''}`}
                  onClick={() => setSelectedMessageUuid(msg.uuid)}
                >
                  <div className="flex items-start gap-4">
                    <div className="flex flex-col gap-1">
                      <Badge variant={msg.type === 'assistant' ? 'primary' : msg.type === 'tool_result' ? 'warning' : 'gray'}>
                        {msg.type}
                      </Badge>
                      {msg.is_error && <Badge variant="error">error</Badge>}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-gray-900">
                        {truncateText(msg.content || '[No content]', 300)}
                      </p>
                      <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-gray-500">
                        <span>{formatDateTime(msg.timestamp)}</span>
                        {msg.model && <span>{msg.model}</span>}
                        {getTotalTokens(msg.tokens) > 0 && (
                          <span>{formatTokens(getTotalTokens(msg.tokens))} tokens</span>
                        )}
                        {msg.tool_names && (
                          <span className="text-primary-600">{msg.tool_names}</span>
                        )}
                      </div>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
          {data && data.total_pages > 1 && (
            <Pagination
              currentPage={page}
              totalPages={data.total_pages}
              onPageChange={onPageChange}
            />
          )}
        </>
      )}

      {/* Message Detail Modal */}
      {selectedMessageUuid && (
        <SubagentMessageDetailModal
          projectHash={projectHash}
          sessionId={sessionId}
          agentId={agentId}
          messageUuid={selectedMessageUuid}
          onClose={() => setSelectedMessageUuid(null)}
          onNavigate={(uuid) => setSelectedMessageUuid(uuid)}
        />
      )}
    </div>
  );
}

function SubagentMessageDetailModal({
  projectHash,
  sessionId,
  agentId,
  messageUuid,
  onClose,
  onNavigate,
}: {
  projectHash: string;
  sessionId: string;
  agentId: string;
  messageUuid: string;
  onClose: () => void;
  onNavigate?: (uuid: string) => void;
}) {
  // We'll reuse the existing MessageDetailModal component but need to adapt the API calls
  // For now, use a slightly adapted version that calls subagent endpoints
  return (
    <MessageDetailModal
      projectHash={projectHash}
      sessionId={sessionId}
      messageUuid={messageUuid}
      onClose={onClose}
      onNavigate={onNavigate}
      // Override the API base path for subagent context
      apiBasePath={`/api/subagents/${projectHash}/${sessionId}/${agentId}`}
    />
  );
}

function ToolsTab({ projectHash, sessionId, agentId }: TabProps) {
  const { data, isLoading } = useSubagentTools(projectHash, sessionId, agentId);

  if (isLoading) return <LoadingSpinner />;

  const tools = data?.tools || [];

  return (
    <div className="space-y-6">
      {tools.length > 0 ? (
        <>
          <div className="card">
            <h3 className="mb-4 text-lg font-semibold text-gray-900">Tool Usage Distribution</h3>
            <ToolUsageChart tools={tools} />
          </div>
          <div className="card overflow-hidden !p-0">
            <table className="w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/50">
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Tool</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Calls</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Avg Duration</th>
                  <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Errors</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {tools.map((tool) => (
                  <tr key={tool.name}>
                    <td className="px-6 py-4 font-medium text-gray-900">{tool.name}</td>
                    <td className="px-6 py-4 text-gray-700">{tool.count}</td>
                    <td className="px-6 py-4 text-gray-700">
                      {tool.avg_duration_seconds > 0 ? `${tool.avg_duration_seconds.toFixed(2)}s` : '-'}
                    </td>
                    <td className="px-6 py-4">
                      {tool.error_count > 0 ? (
                        <Badge variant="error">{tool.error_count}</Badge>
                      ) : (
                        <Badge variant="success">0</Badge>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <div className="card text-center text-gray-500 py-8">No tool usage data available</div>
      )}
    </div>
  );
}

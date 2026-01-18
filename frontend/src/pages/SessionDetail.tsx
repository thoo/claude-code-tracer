import { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import {
  useSession,
  useSessionMetrics,
  useSessionMessages,
  useSessionMessageFilters,
  useSessionTools,
  useSessionSkills,
} from '../hooks/useApi';
import {
  formatCost,
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

type TabType = 'messages' | 'tools' | 'skills';

export default function SessionDetail() {
  const { projectHash, sessionId } = useParams<{ projectHash: string; sessionId: string }>();
  const [activeTab, setActiveTab] = useState<TabType>('messages');
  const [messagePage, setMessagePage] = useState(1);

  const { data: session, isLoading, error, refetch } = useSession(projectHash || '', sessionId || '');
  const { data: metrics } = useSessionMetrics(projectHash || '', sessionId || '');

  if (isLoading) {
    return (
      <div className="py-20">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (error || !session) {
    return (
      <ErrorDisplay
        message={error instanceof Error ? error.message : 'Failed to load session'}
        onRetry={() => refetch()}
      />
    );
  }

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
        <span className="font-medium text-gray-900">{session.slug || sessionId}</span>
      </nav>

      {/* Session header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {session.slug || sessionId}
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Started {formatDateTime(session.start_time)}
            {session.end_time && ` • Ended ${formatDateTime(session.end_time)}`}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {session.skills_used.length > 0 && (
            <div className="flex gap-1">
              {session.skills_used.slice(0, 3).map((skill) => (
                <Badge key={skill} variant="primary">{skill}</Badge>
              ))}
              {session.skills_used.length > 3 && (
                <Badge variant="gray">+{session.skills_used.length - 3}</Badge>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Stats cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5">
        <StatsCard
          title="Duration"
          value={formatDuration(session.duration_seconds)}
        />
        <StatsCard
          title="Messages"
          value={session.message_count}
        />
        <StatsCard
          title="Tool Calls"
          value={session.tool_calls}
        />
        <StatsCard
          title="Tokens"
          value={formatTokens(getTotalTokens(session.tokens))}
          breakdown={[
            { label: 'Input', value: formatTokens(session.tokens.input_tokens) },
            { label: 'Output', value: formatTokens(session.tokens.output_tokens) },
          ]}
        />
        <StatsCard
          title="Cost"
          value={formatCost(session.cost)}
          subtitle={metrics ? `${metrics.cache_hit_rate.toFixed(0)}% cache hit` : undefined}
        />
      </div>

      {/* Additional metrics row */}
      <div className="grid gap-4 sm:grid-cols-4">
        <StatsCard
          title="Subagents"
          value={session.subagent_count}
          subtitle="Spawned during session"
        />
        <StatsCard
          title="Errors"
          value={session.errors}
          subtitle={session.errors > 0 ? 'Tool errors encountered' : 'No errors'}
        />
        {metrics && (
          <StatsCard
            title="Models Used"
            value={metrics.models_used.length}
            subtitle={metrics.models_used.map(m => m.replace('claude-', '').replace(/-\d+$/, '')).join(', ')}
          />
        )}
        {metrics && (
          <StatsCard
            title="Interruption Rate"
            value={`${metrics.interruption_rate.toFixed(1)}%`}
            subtitle="Commands interrupted by user"
          />
        )}
      </div>

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <nav className="-mb-px flex gap-4 overflow-x-auto">
          {(['messages', 'tools', 'skills'] as const).map((tab) => (
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
          page={messagePage}
          onPageChange={setMessagePage}
        />
      )}
      {activeTab === 'tools' && (
        <ToolsTab projectHash={projectHash || ''} sessionId={sessionId || ''} />
      )}
      {activeTab === 'skills' && (
        <SkillsTab projectHash={projectHash || ''} sessionId={sessionId || ''} />
      )}
    </div>
  );
}

interface TabProps {
  projectHash: string;
  sessionId: string;
}

function MessagesTab({ projectHash, sessionId, page, onPageChange }: TabProps & { page: number; onPageChange: (p: number) => void }) {
  const navigate = useNavigate();
  const [typeFilter, setTypeFilter] = useState<string>('');
  const [toolFilter, setToolFilter] = useState<string>('');
  const [errorOnly, setErrorOnly] = useState(false);
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedMessageUuid, setSelectedMessageUuid] = useState<string | null>(null);

  const { data: filterOptions } = useSessionMessageFilters(projectHash, sessionId);
  const { data, isLoading } = useSessionMessages(projectHash, sessionId, {
    page,
    perPage: 20,
    type: typeFilter || undefined,
    tool: toolFilter || undefined,
    errorOnly: errorOnly || undefined,
    search: searchQuery || undefined,
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
            {filterOptions?.types.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
        </div>

        {/* Tool filter */}
        {filterOptions && filterOptions.tools.length > 0 && (
          <div className="flex items-center gap-2">
            <label htmlFor="tool-filter" className="text-sm font-medium text-gray-700">
              Tool:
            </label>
            <select
              id="tool-filter"
              value={toolFilter}
              onChange={(e) => {
                setToolFilter(e.target.value);
                onPageChange(1);
              }}
              className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            >
              <option value="">All tools</option>
              {filterOptions.tools.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name} ({t.count})
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Error only toggle */}
        {filterOptions && filterOptions.error_count > 0 && (
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
            <span className="text-sm font-medium text-gray-700">
              Errors only ({filterOptions.error_count})
            </span>
          </label>
        )}

        {/* Search input */}
        <div className="flex items-center gap-2">
          <label htmlFor="search-input" className="text-sm font-medium text-gray-700">
            Search:
          </label>
          <input
            id="search-input"
            type="text"
            value={searchQuery}
            onChange={(e) => {
              setSearchQuery(e.target.value);
              onPageChange(1);
            }}
            placeholder="Search message content..."
            className="rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 w-64"
          />
        </div>

        {/* Clear filters */}
        {(typeFilter || toolFilter || errorOnly || searchQuery) && (
          <button
            onClick={() => {
              setTypeFilter('');
              setToolFilter('');
              setErrorOnly(false);
              setSearchQuery('');
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
          No messages found{(typeFilter || toolFilter || errorOnly || searchQuery) ? ' matching filters' : ''}
        </div>
      ) : (
        <>
          <div className="card overflow-hidden !p-0">
            <div className="divide-y divide-gray-100">
              {messages.map((msg) => {
                // Parse subagent content if it's a subagent message
                const isSubagent = msg.type === 'subagent';
                let subagentData: { agentId?: string; subagent_type?: string; description?: string; prompt?: string } | null = null;
                if (isSubagent && msg.content) {
                  try {
                    subagentData = typeof msg.content === 'string' ? JSON.parse(msg.content) : msg.content;
                  } catch {
                    subagentData = null;
                  }
                }

                return (
                  <div
                    key={msg.uuid}
                    className={`px-6 py-4 cursor-pointer transition-colors hover:bg-gray-50 ${msg.is_error ? 'bg-red-50 hover:bg-red-100' : ''} ${isSubagent ? 'bg-purple-50/50 hover:bg-purple-100/50' : ''}`}
                    onClick={() => {
                      if (isSubagent && subagentData?.agentId) {
                        navigate(`/subagent/${projectHash}/${sessionId}/${subagentData.agentId}`);
                      } else {
                        setSelectedMessageUuid(msg.uuid);
                      }
                    }}
                  >
                    <div className="flex items-start gap-4">
                      <div className="flex flex-col gap-1">
                        <Badge variant={msg.type === 'assistant' ? 'primary' : msg.type === 'subagent' ? 'secondary' : msg.type === 'tool_result' ? 'warning' : msg.type === 'hook' ? 'gray' : 'gray'}>
                          {msg.type}
                        </Badge>
                        {msg.is_error && <Badge variant="error">error</Badge>}
                      </div>
                      <div className="flex-1 min-w-0">
                        {isSubagent && subagentData ? (
                          <>
                            <div className="flex items-center gap-2 mb-1">
                              <Badge variant="primary">{subagentData.subagent_type || 'unknown'}</Badge>
                              {subagentData.description && (
                                <span className="text-sm font-medium text-gray-900">{subagentData.description}</span>
                              )}
                            </div>
                            {subagentData.prompt && (
                              <p className="text-sm text-gray-600">
                                {truncateText(subagentData.prompt, 200)}
                              </p>
                            )}
                          </>
                        ) : (
                          <p className="text-sm text-gray-900">
                            {truncateText(msg.content || '[No content]', 300)}
                          </p>
                        )}
                        <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-gray-500">
                          <span>{formatDateTime(msg.timestamp)}</span>
                          {msg.model && <span>{msg.model}</span>}
                          {getTotalTokens(msg.tokens) > 0 && (
                            <span>{formatTokens(getTotalTokens(msg.tokens))} tokens</span>
                          )}
                          {msg.tool_names && !isSubagent && (
                            <span className="text-primary-600">{msg.tool_names}</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })}
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
        <MessageDetailModal
          projectHash={projectHash}
          sessionId={sessionId}
          messageUuid={selectedMessageUuid}
          onClose={() => setSelectedMessageUuid(null)}
          onNavigate={(uuid) => setSelectedMessageUuid(uuid)}
        />
      )}
    </div>
  );
}

function ToolsTab({ projectHash, sessionId }: TabProps) {
  const { data, isLoading } = useSessionTools(projectHash, sessionId);

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

function SkillsTab({ projectHash, sessionId }: TabProps) {
  const { data: skills, isLoading } = useSessionSkills(projectHash, sessionId);

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      {skills && skills.skills.length > 0 ? (
        <div className="card">
          <h3 className="mb-4 font-semibold text-gray-900">Skills Used</h3>
          <div className="flex flex-wrap gap-2">
            {skills.skills.map((skill) => (
              <div key={skill.skill_name} className="flex items-center gap-2 rounded-lg bg-gray-50 px-3 py-2">
                <Badge variant="primary">{skill.skill_name}</Badge>
                <span className="text-sm text-gray-500">{skill.invocation_count}x</span>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="card text-center text-gray-500 py-8">No skills used in this session</div>
      )}
    </div>
  );
}

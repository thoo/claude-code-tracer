import { useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import {
  useSession,
  useSessionMetrics,
  useSessionMessages,
  useSessionTools,
  useSessionSubagents,
  useSessionSkills,
  useSessionCodeChanges,
  useSessionCommands,
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

type TabType = 'messages' | 'tools' | 'commands' | 'subagents' | 'code';

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
          {(['messages', 'tools', 'commands', 'subagents', 'code'] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`whitespace-nowrap border-b-2 pb-3 text-sm font-medium capitalize transition-colors ${
                activeTab === tab
                  ? 'border-primary-500 text-primary-600'
                  : 'border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700'
              }`}
            >
              {tab === 'code' ? 'Code Changes' : tab}
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
      {activeTab === 'commands' && (
        <CommandsTab projectHash={projectHash || ''} sessionId={sessionId || ''} />
      )}
      {activeTab === 'subagents' && (
        <SubagentsTab projectHash={projectHash || ''} sessionId={sessionId || ''} />
      )}
      {activeTab === 'code' && (
        <CodeChangesTab projectHash={projectHash || ''} sessionId={sessionId || ''} />
      )}
    </div>
  );
}

interface TabProps {
  projectHash: string;
  sessionId: string;
}

function MessagesTab({ projectHash, sessionId, page, onPageChange }: TabProps & { page: number; onPageChange: (p: number) => void }) {
  const { data, isLoading } = useSessionMessages(projectHash, sessionId, { page, perPage: 20 });

  if (isLoading) return <LoadingSpinner />;

  const messages = data?.messages || [];

  return (
    <div className="space-y-4">
      <div className="card overflow-hidden !p-0">
        <div className="divide-y divide-gray-100">
          {messages.map((msg) => (
            <div key={msg.uuid} className="px-6 py-4">
              <div className="flex items-start gap-4">
                <Badge variant={msg.type === 'assistant' ? 'primary' : 'gray'}>
                  {msg.type}
                </Badge>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-900">
                    {truncateText(msg.content || '[No content]', 300)}
                  </p>
                  <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
                    <span>{formatDateTime(msg.timestamp)}</span>
                    {msg.model && <span>{msg.model}</span>}
                    {getTotalTokens(msg.tokens) > 0 && (
                      <span>{formatTokens(getTotalTokens(msg.tokens))} tokens</span>
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

function CommandsTab({ projectHash, sessionId }: TabProps) {
  const { data, isLoading } = useSessionCommands(projectHash, sessionId);

  if (isLoading) return <LoadingSpinner />;

  const commands = data?.commands || [];
  const summary = data?.summary;

  return (
    <div className="space-y-6">
      {summary && (
        <div className="grid gap-4 sm:grid-cols-3">
          <StatsCard title="Total Commands" value={summary.total_commands} />
          <StatsCard title="Interruption Rate" value={`${summary.interruption_rate.toFixed(1)}%`} />
          <StatsCard title="Avg Steps/Command" value={summary.avg_steps_per_command.toFixed(1)} />
        </div>
      )}
      <div className="card overflow-hidden !p-0">
        <div className="divide-y divide-gray-100">
          {commands.map((cmd, idx) => (
            <div key={idx} className="px-6 py-4">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-900">{truncateText(cmd.user_message, 200)}</p>
                  <p className="mt-1 text-xs text-gray-500">{formatDateTime(cmd.timestamp)}</p>
                </div>
                {cmd.followed_by_interruption && (
                  <Badge variant="warning">Interrupted</Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function SubagentsTab({ projectHash, sessionId }: TabProps) {
  const { data, isLoading } = useSessionSubagents(projectHash, sessionId);

  if (isLoading) return <LoadingSpinner />;

  const subagents = data?.subagents || [];

  if (subagents.length === 0) {
    return <div className="card text-center text-gray-500 py-8">No subagents spawned in this session</div>;
  }

  return (
    <div className="card overflow-hidden !p-0">
      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-100 bg-gray-50/50">
            <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Type</th>
            <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Description</th>
            <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Status</th>
            <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Tool Calls</th>
            <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">Tokens</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {subagents.map((agent) => (
            <tr key={agent.agent_id}>
              <td className="px-6 py-4">
                <Badge variant="primary">{agent.subagent_type}</Badge>
              </td>
              <td className="px-6 py-4 text-sm text-gray-700 max-w-xs truncate">
                {agent.description || '-'}
              </td>
              <td className="px-6 py-4">
                <Badge variant={agent.status === 'completed' ? 'success' : agent.status === 'error' ? 'error' : 'warning'}>
                  {agent.status}
                </Badge>
              </td>
              <td className="px-6 py-4 text-gray-700">{agent.tool_calls}</td>
              <td className="px-6 py-4 text-gray-700">{formatTokens(getTotalTokens(agent.tokens))}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CodeChangesTab({ projectHash, sessionId }: TabProps) {
  const { data, isLoading } = useSessionCodeChanges(projectHash, sessionId);
  const { data: skills } = useSessionSkills(projectHash, sessionId);

  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      {/* Code changes summary */}
      {data && (
        <>
          <div className="grid gap-4 sm:grid-cols-4">
            <StatsCard title="Files Created" value={data.files_created} />
            <StatsCard title="Files Modified" value={data.files_modified} />
            <StatsCard title="Lines Added" value={`+${data.lines_added}`} />
            <StatsCard title="Lines Removed" value={`-${data.lines_removed}`} />
          </div>
          {data.changes_by_file.length > 0 && (
            <div className="card overflow-hidden !p-0">
              <div className="border-b border-gray-100 px-6 py-4">
                <h3 className="font-semibold text-gray-900">Files Changed</h3>
              </div>
              <div className="divide-y divide-gray-100">
                {data.changes_by_file.map((file, idx) => (
                  <div key={idx} className="flex items-center justify-between px-6 py-3">
                    <div className="flex items-center gap-3">
                      <Badge variant={file.operation === 'Write' ? 'success' : 'primary'}>
                        {file.operation}
                      </Badge>
                      <span className="text-sm font-mono text-gray-700 truncate max-w-md">
                        {file.file_path}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 text-sm">
                      {file.lines_added > 0 && (
                        <span className="text-green-600">+{file.lines_added}</span>
                      )}
                      {file.lines_removed > 0 && (
                        <span className="text-red-600">-{file.lines_removed}</span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Skills used */}
      {skills && skills.skills.length > 0 && (
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
      )}
    </div>
  );
}

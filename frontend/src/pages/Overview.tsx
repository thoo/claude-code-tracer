import { Link } from 'react-router-dom';
import { useProjects } from '../hooks/useApi';
import { formatCost, formatTokens, formatDate, formatRelativeTime, getProjectName } from '../lib/formatting';
import LoadingSpinner from '../components/common/LoadingSpinner';
import ErrorDisplay from '../components/common/ErrorDisplay';
import EmptyState from '../components/common/EmptyState';
import StatsCard from '../components/common/StatsCard';
import type { Project } from '../types';

export default function Overview() {
  const { data, isLoading, error, refetch } = useProjects();

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
        message={error instanceof Error ? error.message : 'Failed to load projects'}
        onRetry={() => refetch()}
      />
    );
  }

  const projects = data?.projects || [];

  if (projects.length === 0) {
    return (
      <EmptyState
        icon={
          <svg className="h-8 w-8" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
            />
          </svg>
        }
        title="No projects found"
        description="Start using Claude Code to see your session analytics here."
      />
    );
  }

  // Calculate global stats
  const globalStats = calculateGlobalStats(projects);

  return (
    <div className="space-y-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Overview</h1>
        <p className="mt-1 text-sm text-gray-500">
          Analytics across all your Claude Code projects
        </p>
      </div>

      {/* Global stats cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Total Projects"
          value={globalStats.totalProjects}
          icon={
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
              />
            </svg>
          }
        />
        <StatsCard
          title="Total Sessions"
          value={globalStats.totalSessions}
          icon={
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
          }
        />
        <StatsCard
          title="Total Tokens"
          value={formatTokens(globalStats.totalTokens)}
          subtitle={`${formatTokens(globalStats.totalCacheCreation)} create · ${formatTokens(globalStats.totalCacheRead)} read`}
          icon={
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"
              />
            </svg>
          }
        />
        <StatsCard
          title="Total Cost"
          value={formatCost(globalStats.totalCost)}
          icon={
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          }
        />
      </div>

      {/* Projects table */}
      <div className="card overflow-hidden !p-0">
        <div className="border-b border-gray-100 px-6 py-4">
          <h2 className="text-lg font-semibold text-gray-900">Projects</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/50">
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Project
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Sessions
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Tokens
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Cost
                </th>
                <th className="px-6 py-3 text-left text-xs font-medium uppercase tracking-wider text-gray-500">
                  Last Activity
                </th>
                <th className="px-6 py-3 text-right text-xs font-medium uppercase tracking-wider text-gray-500">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {projects.map((project) => (
                <ProjectRow key={project.path_hash} project={project} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

interface ProjectRowProps {
  project: Project;
}

function ProjectRow({ project }: ProjectRowProps) {
  const projectName = getProjectName(project.project_path);

  return (
    <tr className="transition-colors hover:bg-gray-50/50">
      <td className="px-6 py-4">
        <div>
          <div className="font-medium text-gray-900">{projectName}</div>
          <div className="text-sm text-gray-500 truncate max-w-xs" title={project.project_path}>
            {project.project_path}
          </div>
        </div>
      </td>
      <td className="px-6 py-4 text-sm text-gray-700">{project.session_count}</td>
      <td className="px-6 py-4 text-sm text-gray-700">
        <div>{formatTokens(project.total_tokens)}</div>
        <div className="text-xs text-gray-400">
          {formatTokens(project.tokens.cache_creation_input_tokens)} create · {formatTokens(project.tokens.cache_read_input_tokens)} read
        </div>
      </td>
      <td className="px-6 py-4 text-sm text-gray-700">{formatCost(project.total_cost)}</td>
      <td className="px-6 py-4 text-sm text-gray-500">
        <div title={formatDate(project.last_activity)}>
          {formatRelativeTime(project.last_activity)}
        </div>
      </td>
      <td className="px-6 py-4 text-right">
        <Link
          to={`/project/${project.path_hash}`}
          className="inline-flex items-center gap-1 text-sm font-medium text-primary-600 hover:text-primary-700"
        >
          View
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </Link>
      </td>
    </tr>
  );
}

function calculateGlobalStats(projects: Project[]) {
  return {
    totalProjects: projects.length,
    totalSessions: projects.reduce((sum, p) => sum + p.session_count, 0),
    totalTokens: projects.reduce((sum, p) => sum + p.total_tokens, 0),
    totalCacheCreation: projects.reduce((sum, p) => sum + p.tokens.cache_creation_input_tokens, 0),
    totalCacheRead: projects.reduce((sum, p) => sum + p.tokens.cache_read_input_tokens, 0),
    totalCost: projects.reduce((sum, p) => sum + p.total_cost, 0),
  };
}

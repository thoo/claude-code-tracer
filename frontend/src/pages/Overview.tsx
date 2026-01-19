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
      <div className="space-y-1">
        <h1 className="text-3xl font-bold text-gray-900 dark:text-surface-100 tracking-tight">Overview</h1>
        <p className="text-gray-600 dark:text-surface-400">
          Analytics across all your Claude Code projects
        </p>
      </div>

      {/* Global stats cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatsCard
          title="Total Projects"
          value={globalStats.totalProjects}
          variant="accent"
          icon={
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"
              />
            </svg>
          }
        />
        <StatsCard
          title="Total Sessions"
          value={globalStats.totalSessions}
          icon={
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"
              />
            </svg>
          }
        />
        <StatsCard
          title="Total Tokens"
          value={formatTokens(globalStats.totalTokens)}
          subtitle={`${formatTokens(globalStats.totalCacheRead)} cached`}
          icon={
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z"
              />
            </svg>
          }
        />
        <StatsCard
          title="Total Cost"
          value={formatCost(globalStats.totalCost)}
          variant="highlight"
          icon={
            <svg className="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
              />
            </svg>
          }
        />
      </div>

      {/* Projects table */}
      <div className="space-y-4">
        <h2 className="text-xl font-semibold text-gray-900 dark:text-surface-100">Projects</h2>
        <div className="table-container">
          <table className="w-full">
            <thead className="table-header">
              <tr>
                <th>Project</th>
                <th>Sessions</th>
                <th>Tokens</th>
                <th>Cost</th>
                <th>Last Activity</th>
              </tr>
            </thead>
            <tbody>
              {projects.map((project, index) => (
                <ProjectRow key={project.path_hash} project={project} index={index} />
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
  index: number;
}

function ProjectRow({ project, index }: ProjectRowProps) {
  const projectName = getProjectName(project.project_path);

  return (
    <tr
      className="table-row animate-fade-in"
      style={{ animationDelay: `${index * 0.05}s` }}
    >
      <td>
        <Link to={`/project/${project.path_hash}`} className="block group">
          <div className="font-medium text-gray-900 dark:text-surface-100 group-hover:text-accent-600 dark:group-hover:text-accent-400 transition-colors">
            {projectName}
          </div>
          <div className="text-sm text-gray-500 dark:text-surface-400 font-mono truncate max-w-xs" title={project.project_path}>
            {project.project_path}
          </div>
        </Link>
      </td>
      <td>
        <span className="font-mono text-gray-700 dark:text-surface-200">{project.session_count}</span>
      </td>
      <td>
        <div className="font-mono text-gray-700 dark:text-surface-200">{formatTokens(project.total_tokens)}</div>
        <div className="text-xs text-gray-500 dark:text-surface-400 font-mono">
          {formatTokens(project.tokens.cache_read_input_tokens)} cached
        </div>
      </td>
      <td>
        <span className="font-mono text-gray-700 dark:text-surface-200">{formatCost(project.total_cost)}</span>
      </td>
      <td>
        <div className="text-gray-600 dark:text-surface-300" title={formatDate(project.last_activity)}>
          {formatRelativeTime(project.last_activity)}
        </div>
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

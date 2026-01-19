# Claude Code Tracer - Frontend

React-based analytics dashboard for visualizing Claude Code session data. Built with Vite, TypeScript, and Tailwind CSS.

## Project Structure

```
src/
├── App.tsx                 # Router setup
├── main.tsx                # Entry point
├── types/
│   └── index.ts            # TypeScript interfaces
├── pages/
│   ├── Overview.tsx        # Global dashboard with all projects
│   ├── ProjectDashboard.tsx # Project-level metrics and sessions
│   ├── SessionDetail.tsx   # Session messages and analytics
│   └── SubagentDetail.tsx  # Subagent message viewer
├── components/
│   ├── common/             # Reusable UI components
│   │   ├── Layout.tsx      # App shell with navigation
│   │   ├── StatsCard.tsx   # Metric display cards
│   │   ├── Pagination.tsx  # Page navigation
│   │   ├── LoadingSpinner.tsx
│   │   ├── ErrorDisplay.tsx
│   │   ├── EmptyState.tsx
│   │   └── Badge.tsx
│   ├── charts/             # Recharts visualizations
│   │   ├── TokenUsageChart.tsx
│   │   ├── CostChart.tsx
│   │   ├── ToolUsageChart.tsx
│   │   └── ModelUsageChart.tsx
│   └── MessageDetailModal.tsx
├── hooks/
│   └── useApi.ts           # React Query hooks
└── lib/
    ├── api.ts              # API client
    └── formatting.ts       # Display formatters
```

## Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` | Overview | Global stats, project list |
| `/project/:hash` | ProjectDashboard | Sessions list, project metrics, charts |
| `/session/:hash/:id` | SessionDetail | Message timeline, tool usage, errors |
| `/subagent/:hash/:sessionId/:agentId` | SubagentDetail | Subagent messages |

## Features

- **Project Overview** - Aggregate stats across all projects (tokens, cost, sessions)
- **Session Browser** - View all sessions with status, duration, and metrics
- **Message Timeline** - Paginated messages with filtering by type, tool, errors
- **Message Detail Modal** - Full message content, tool inputs/outputs, syntax highlighting
- **Charts** - Token usage, cost breakdown, tool usage, model distribution
- **Subagent Viewer** - Navigate into spawned subagent conversations
- **Dark/Light friendly** - Clean UI with Tailwind CSS

## Setup

```bash
# Install dependencies
npm install

# Run development server (proxies to backend on port 8420)
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Lint
npm run lint
```

## Environment

The frontend proxies API requests to the backend. Configure in `vite.config.ts`:

```ts
server: {
  proxy: {
    '/api': 'http://localhost:8420'
  }
}
```

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool and dev server
- **Tailwind CSS** - Styling
- **React Router** - Client-side routing
- **React Query** - Data fetching and caching
- **Recharts** - Charts and visualizations
- **react-markdown** - Markdown rendering
- **react-syntax-highlighter** - Code highlighting
- **date-fns** - Date formatting

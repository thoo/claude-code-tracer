# Claude Code Tracer

Analytics dashboard for visualizing Claude Code session traces. Provides detailed insights into token usage, costs, tool usage patterns, subagent activity, and code changes across your Claude Code sessions.

## Features

### Core Analytics
- **Project Overview** - View all projects with aggregated stats (cost, tokens, sessions)
- **Session Timeline** - Detailed view of conversation flow with tool calls
- **Token Metrics** - Input/output tokens, cache creation/read stats, cost breakdown
- **Tool Usage** - Frequency analysis of all tools used (Read, Edit, Bash, etc.)

### Advanced Tracking
- **Subagent Tracking** - Monitor spawned subagents (Explore, Plan, Bash agents)
- **Skill Usage** - Track invoked skills (/commit, /review-pr, etc.)
- **Code Changes** - Lines added/removed, files created/modified
- **Error Analysis** - Track and categorize errors across sessions
- **User Commands** - Analyze command patterns and interruption rates

### Metrics & Insights
- Daily token/cost trends
- Cache hit rate analysis
- Model usage distribution
- Command complexity over time

## Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   React + Vite  │────▶│  FastAPI Backend │────▶│  ~/.claude/     │
│   (Frontend)    │◀────│  (Python)        │◀────│  (JSONL logs)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

- **Backend**: Python FastAPI with Pydantic models, DuckDB for querying JSONL logs
- **Frontend**: React + Vite + TailwindCSS + Recharts (planned)
- **Data Source**: Claude Code session logs from `~/.claude/projects/`

## Quick Start

### Backend

```bash
cd backend

# Install dependencies (requires uv)
uv venv
uv pip install -e ".[dev]"

# Run development server
uv run uvicorn claude_code_tracer.main:app --reload

# Server runs at http://localhost:8000
# API docs at http://localhost:8000/docs
```

### Frontend (Coming Soon)

```bash
cd frontend
npm install
npm run dev
```

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/projects` | List all projects with stats |
| `GET /api/projects/{hash}/sessions` | List sessions for a project |
| `GET /api/sessions/{hash}/{id}/messages` | Paginated messages with filters |
| `GET /api/sessions/{hash}/{id}/tools` | Tool usage breakdown |
| `GET /api/sessions/{hash}/{id}/metrics` | Token usage and costs |
| `GET /api/sessions/{hash}/{id}/subagents` | Subagent tracking |
| `GET /api/sessions/{hash}/{id}/skills` | Skills invoked |
| `GET /api/sessions/{hash}/{id}/code-changes` | Lines written/modified |
| `GET /api/sessions/{hash}/{id}/errors` | Error analysis |
| `GET /api/sessions/{hash}/{id}/commands` | User commands with stats |
| `GET /api/metrics/daily/{hash}` | Daily aggregated metrics |
| `GET /api/metrics/aggregate` | Cross-project aggregate stats |
| `GET /api/metrics/pricing` | Model pricing information |

## Development

```bash
cd backend

# Run linting
uv run ruff check src/
uv run ruff format src/

# Run type checking
uv run mypy src/

# Run tests
uv run pytest

# Install pre-commit hooks
uv run pre-commit install
```

## Project Structure

```
claude-code-tracer/
├── backend/
│   ├── src/claude_code_tracer/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── models/
│   │   │   ├── entries.py       # Log entry models
│   │   │   └── responses.py     # API response models
│   │   ├── routers/
│   │   │   ├── sessions.py      # Session/project endpoints
│   │   │   ├── metrics.py       # Metrics endpoints
│   │   │   └── subagents.py     # Subagent endpoints
│   │   └── services/
│   │       ├── database.py      # DuckDB connection management
│   │       ├── queries.py       # SQL query templates
│   │       ├── metrics.py       # Cost calculation
│   │       └── log_parser.py    # JSONL parsing
│   └── tests/
├── frontend/                     # React app (planned)
├── docs/
└── .pre-commit-config.yaml
```

## Data Sources

Claude Code Tracer reads session data from:

- **Projects**: `~/.claude/projects/`
- **Sessions**: `~/.claude/projects/{hash}/*.jsonl`
- **Sessions Index**: `~/.claude/projects/{hash}/sessions-index.json`
- **Subagent Logs**: `~/.claude/projects/{hash}/subagents/agent-{id}.jsonl`

## Model Pricing

Current pricing (per million tokens):

| Model | Input | Output | Cache Create | Cache Read |
|-------|-------|--------|--------------|------------|
| claude-opus-4-5 | $15.00 | $75.00 | $18.75 | $1.50 |
| claude-sonnet-4 | $3.00 | $15.00 | $3.75 | $0.30 |
| claude-3-5-haiku | $1.00 | $5.00 | $1.25 | $0.10 |

## License

MIT

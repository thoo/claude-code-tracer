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
- **Error Analysis** - Track and categorize errors across sessions

### Metrics & Insights
- Daily token/cost trends
- Cache hit rate analysis
- Model usage distribution
- Tool execution time

## Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   React + Vite  │────▶│  FastAPI Backend │────▶│  ~/.claude/     │
│   (Frontend)    │◀────│  (Python)        │◀────│  (JSONL logs)   │
└─────────────────┘     └──────────────────┘     └─────────────────┘
```

- **Backend**: Python FastAPI with Pydantic models, DuckDB for querying JSONL logs
- **Frontend**: React + Vite + TailwindCSS + Recharts
- **Data Source**: Claude Code session logs from `~/.claude/projects/`

## Installation

### Using pip

```bash
pip install claude-code-tracer

# Run the dashboard
cctracer
```

### Using uv

```bash
uv tool install claude-code-tracer

# Run the dashboard
cctracer
```

## Usage

```bash
cctracer                  # Start server, opens browser at http://localhost:8420
cctracer --port 9000      # Custom port
cctracer --no-browser     # Don't auto-open browser
cctracer --help           # Show all options
```

The dashboard automatically reads sessions from `~/.claude/projects/`.

## Development Setup

### Backend

```bash
cd backend

# Install dependencies
uv sync --all-extras

# Run development server
uv run uvicorn claude_code_tracer.main:app --reload --port 8420

# Server runs at http://localhost:8420
# API docs at http://localhost:8420/docs
```

### Frontend

```bash
cd frontend
npm install
npm run dev   # Runs at http://localhost:5173, proxies API to :8420
```

### Using Makefile

```bash
make install   # Install all dependencies
make dev       # Run frontend + backend dev servers
make build     # Build for distribution
make test      # Run tests
make check     # Lint + test
```

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
├── frontend/                     # React dashboard
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

Current pricing (per million tokens) - [Source](https://docs.anthropic.com/en/docs/about-claude/models):

| Model | Input | Output | Cache Write | Cache Read |
|-------|-------|--------|-------------|------------|
| Claude Opus 4.5 | $5.00 | $25.00 | $6.25 | $0.50 |
| Claude Sonnet 4.5 | $3.00 | $15.00 | $3.75 | $0.30 |
| Claude Haiku 4.5 | $1.00 | $5.00 | $1.25 | $0.10 |

## License

MIT

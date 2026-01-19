# Claude Code Tracer - Backend

FastAPI-based analytics API for Claude Code sessions. Reads session data from `~/.claude/projects/` and provides endpoints for viewing metrics, messages, tool usage, and subagent activity.

## Installation

```bash
# Using pip
pip install claude-code-tracer

# Using uv
uv tool install claude-code-tracer

# Run the dashboard
cctracer
```

## Project Structure

```
src/claude_code_tracer/
├── main.py              # FastAPI app entry point
├── routers/
│   ├── sessions.py      # Session and message endpoints
│   ├── metrics.py       # Aggregated metrics endpoints
│   └── subagents.py     # Subagent-specific endpoints
├── models/
│   ├── entries.py       # Base data models (TokenUsage, ToolUse)
│   └── responses.py     # API response models
└── services/
    ├── database.py      # DuckDB connection, file discovery
    ├── log_parser.py    # JSONL session parsing
    ├── metrics.py       # Cost calculation, pricing
    └── queries.py       # DuckDB SQL queries
```

## API Endpoints

### Projects

| Endpoint | Description |
|----------|-------------|
| `GET /api/projects` | List all projects with aggregated metrics |
| `GET /api/projects/{hash}/sessions` | List sessions for a project |
| `GET /api/projects/{hash}/metrics` | Aggregated metrics across all sessions |
| `GET /api/projects/{hash}/tools` | Tool usage across all sessions |

### Sessions

| Endpoint | Description |
|----------|-------------|
| `GET /api/sessions/{hash}/{id}` | Session details |
| `GET /api/sessions/{hash}/{id}/messages` | Paginated messages (supports filtering) |
| `GET /api/sessions/{hash}/{id}/messages/filters` | Available filter options |
| `GET /api/sessions/{hash}/{id}/messages/{uuid}` | Single message detail |
| `GET /api/sessions/{hash}/{id}/messages/by-index/{idx}` | Message by index |
| `GET /api/sessions/{hash}/{id}/metrics` | Session metrics |
| `GET /api/sessions/{hash}/{id}/tools` | Tool usage stats |
| `GET /api/sessions/{hash}/{id}/subagents` | Subagents spawned |
| `GET /api/sessions/{hash}/{id}/skills` | Skills invoked |
| `GET /api/sessions/{hash}/{id}/code-changes` | File changes |
| `GET /api/sessions/{hash}/{id}/errors` | Error entries |
| `GET /api/sessions/{hash}/{id}/commands` | User commands |

### Subagents

| Endpoint | Description |
|----------|-------------|
| `GET /api/subagents/{hash}/{agent_id}` | Subagent details |
| `GET /api/subagents/{hash}/{agent_id}/tools` | Subagent tool usage |
| `GET /api/subagents/{hash}/{session_id}/{agent_id}` | Subagent within session context |
| `GET /api/subagents/{hash}/{session_id}/{agent_id}/messages` | Subagent messages |

### Metrics

| Endpoint | Description |
|----------|-------------|
| `GET /api/metrics/pricing` | Current model pricing (from LiteLLM) |
| `GET /api/metrics/daily/{hash}` | Daily metrics for a project |
| `GET /api/metrics/aggregate` | Global or per-project aggregates |

### Health

| Endpoint | Description |
|----------|-------------|
| `GET /` | API info |
| `GET /health` | Health check |

## CLI Usage

```bash
cctracer                  # Start server, opens browser at http://localhost:8420
cctracer --port 9000      # Custom port
cctracer --no-browser     # Don't auto-open browser
cctracer --reload         # Enable auto-reload for development
```

## Development Setup

```bash
# Install dependencies
uv sync --all-extras

# Run development server
uv run uvicorn claude_code_tracer.main:app --reload --port 8420

# Or use the CLI with reload
uv run cctracer --reload

# API docs at http://localhost:8420/docs
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CLAUDE_DIR` | `~/.claude` | Claude data directory |

## Development

```bash
# Linting and formatting
uv run ruff check .
uv run ruff format .

# Type checking
uv run mypy src/

# Run tests
uv run pytest
```

## Tech Stack

- **FastAPI** - Web framework
- **DuckDB** - In-memory SQL for querying JSONL files
- **Pydantic** - Data validation and serialization
- **orjson** - Fast JSON parsing
- **httpx** - HTTP client for fetching pricing data

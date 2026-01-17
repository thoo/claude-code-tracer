# Claude Code Tracer - Backend

Analytics dashboard API for Claude Code sessions.

## Setup

```bash
# Install dependencies
uv venv
uv pip install -e ".[dev]"

# Run development server
uv run uvicorn claude_code_tracer.main:app --reload

# Or with the standard activate workflow
source .venv/bin/activate
uvicorn claude_code_tracer.main:app --reload
```

## API Documentation

Once running, visit http://localhost:8000/docs for interactive API documentation.

## Development

```bash
# Run linting
uv run ruff check .
uv run ruff format .

# Run type checking
uv run mypy src/

# Run tests
uv run pytest
```

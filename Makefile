.PHONY: help install dev frontend backend build clean test lint format check run

# Default port
PORT ?= 8420

help:
	@echo "Claude Code Tracer - Build Commands"
	@echo ""
	@echo "Development:"
	@echo "  make install    Install all dependencies (frontend + backend)"
	@echo "  make dev        Run both frontend and backend dev servers"
	@echo "  make frontend   Run frontend dev server only"
	@echo "  make backend    Run backend dev server only"
	@echo ""
	@echo "Build & Package:"
	@echo "  make build      Build frontend and bundle into backend package"
	@echo "  make package    Build Python wheel package"
	@echo "  make clean      Remove build artifacts"
	@echo ""
	@echo "Quality:"
	@echo "  make test       Run backend tests"
	@echo "  make lint       Run linters (ruff, mypy)"
	@echo "  make format     Format code with ruff"
	@echo "  make check      Run all checks (lint + test)"
	@echo ""
	@echo "Run:"
	@echo "  make run        Run the bundled app (after make build)"

# =============================================================================
# Development
# =============================================================================

install:
	cd frontend && npm install
	cd backend && uv sync --all-extras

frontend:
	cd frontend && npm run dev

backend:
	cd backend && uv run uvicorn claude_code_tracer.main:app --reload --port $(PORT)

dev:
	@echo "Starting frontend and backend dev servers..."
	@echo "Frontend: http://localhost:5173"
	@echo "Backend:  http://localhost:$(PORT)"
	@make -j2 frontend backend

# =============================================================================
# Build & Package
# =============================================================================

build: clean-static build-frontend bundle-frontend
	@echo "Build complete! Run 'make run' to start the app."

build-frontend:
	cd frontend && npm run build

bundle-frontend:
	@echo "Bundling frontend into backend package..."
	rm -rf backend/src/claude_code_tracer/static/*
	cp -r frontend/dist/* backend/src/claude_code_tracer/static/
	@echo "Frontend bundled to backend/src/claude_code_tracer/static/"

package: build
	cd backend && uv build
	@echo "Package built: backend/dist/"

clean: clean-static
	rm -rf frontend/dist
	rm -rf backend/dist
	rm -rf backend/.pytest_cache
	rm -rf backend/.mypy_cache
	rm -rf backend/.ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

clean-static:
	@# Keep .gitkeep but remove everything else
	find backend/src/claude_code_tracer/static -mindepth 1 ! -name '.gitkeep' -exec rm -rf {} + 2>/dev/null || true

# =============================================================================
# Quality
# =============================================================================

test:
	cd backend && uv run pytest

lint:
	cd backend && uv run ruff check src/ tests/
	cd backend && uv run mypy src/

format:
	cd backend && uv run ruff format src/ tests/
	cd backend && uv run ruff check --fix src/ tests/

check: lint test

# =============================================================================
# Run
# =============================================================================

run:
	cd backend && uv run cctracer --port $(PORT)

# =============================================================================
# Publish
# =============================================================================

publish-test: build
	@echo "Publishing to TestPyPI..."
	cd backend && uv publish --publish-url https://test.pypi.org/legacy/ --token $(UV_PUBLISH_TEST_TOKEN)

publish: build
	@echo "Publishing to PyPI..."
	cd backend && uv publish --token $(UV_PUBLISH_TOKEN)

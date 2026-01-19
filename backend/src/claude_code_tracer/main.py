"""FastAPI application entry point for Claude Code Tracer."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .routers import metrics, sessions, subagents
from .services.cache import get_persistent_cache
from .services.database import DuckDBPool, cleanup_stale_views
from .services.index import get_global_index
from .services.metrics import init_pricing

# Static files directory for bundled frontend
STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Handle application startup and shutdown."""
    logger.info("Starting Claude Code Tracer API")
    init_pricing()

    # Warm up DuckDB connection
    conn = DuckDBPool.get_connection()
    conn.execute("SELECT 1")
    logger.info("DuckDB connection ready")

    # Initialize persistent cache (loads from disk)
    cache = get_persistent_cache()
    logger.info("Persistent cache initialized")

    # Start background index scanner (Priority 4.1)
    index = get_global_index()
    await index.start_background_scanner()
    logger.info("Background index scanner started")

    yield

    logger.info("Shutting down Claude Code Tracer API")

    # Stop background scanner
    await index.stop_background_scanner()

    # Save persistent cache to disk
    cache.save()
    logger.info("Persistent cache saved")

    # Clean up session views before closing connection
    cleaned = cleanup_stale_views()
    if cleaned:
        logger.info(f"Cleaned up {cleaned} stale session views")
    DuckDBPool.close()


app = FastAPI(
    title="Claude Code Tracer",
    description="Analytics dashboard API for Claude Code sessions",
    version="0.1.0",
    lifespan=lifespan,
    default_response_class=ORJSONResponse,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:8420",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:8420",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(metrics.router)
app.include_router(subagents.router)


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


# Mount static files for bundled frontend (must be after API routes)
# Check if static directory has content (not just .gitkeep)
def _has_frontend_build() -> bool:
    """Check if frontend build exists in static directory."""
    if not STATIC_DIR.exists():
        return False
    files = list(STATIC_DIR.iterdir())
    # Has more than just .gitkeep
    return len(files) > 1 or (len(files) == 1 and files[0].name != ".gitkeep")


if _has_frontend_build():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    logger.info(f"Serving frontend from {STATIC_DIR}")
else:

    @app.get("/")
    async def root() -> dict[str, str]:
        """Root endpoint (API-only mode)."""
        return {"message": "Claude Code Tracer API", "docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("claude_code_tracer.main:app", host="0.0.0.0", port=8420, reload=True)

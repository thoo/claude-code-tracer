"""FastAPI application entry point for Claude Code Tracer."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import metrics, sessions, subagents

app = FastAPI(
    title="Claude Code Tracer",
    description="Analytics dashboard API for Claude Code sessions",
    version="0.1.0",
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(sessions.router)
app.include_router(metrics.router)
app.include_router(subagents.router)


@app.get("/")
async def root() -> dict[str, str]:
    """Root endpoint."""
    return {"message": "Claude Code Tracer API", "docs": "/docs"}


@app.get("/health")
async def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("claude_code_tracer.main:app", host="0.0.0.0", port=8000, reload=True)

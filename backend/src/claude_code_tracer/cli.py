"""CLI entry point for Claude Code Tracer."""

import argparse
import webbrowser
from threading import Timer

import uvicorn
from loguru import logger

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8420


def open_browser(url: str) -> None:
    """Open the browser after a short delay."""
    webbrowser.open(url)


def main() -> None:
    """Run the Claude Code Tracer server."""
    parser = argparse.ArgumentParser(
        prog="cctracer",
        description="Claude Code Tracer - Analytics dashboard for Claude Code sessions",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Host to bind to (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind to (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Don't open browser automatically",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )

    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}"
    logger.info(f"Starting Claude Code Tracer at {url}")

    if not args.no_browser:
        # Open browser after a short delay to allow server to start
        Timer(1.5, open_browser, args=[url]).start()

    uvicorn.run(
        "claude_code_tracer.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()

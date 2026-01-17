"""Metrics computation service."""

from ..models.entries import TokenUsage
from ..models.responses import CostBreakdown

# Claude pricing per million tokens (as of January 2026)
# Source: https://docs.anthropic.com/en/docs/about-claude/models#model-comparison-table
PRICING: dict[str, dict[str, float]] = {
    # Claude 4.x models
    "claude-opus-4-5-20250514": {
        "input": 5.0,
        "output": 25.0,
        "cache_create": 6.25,
        "cache_read": 0.50,
    },
    "claude-opus-4-1-20250414": {
        "input": 15.0,
        "output": 75.0,
        "cache_create": 18.75,
        "cache_read": 1.50,
    },
    "claude-opus-4-20250514": {
        "input": 15.0,
        "output": 75.0,
        "cache_create": 18.75,
        "cache_read": 1.50,
    },
    "claude-sonnet-4-5-20250514": {
        "input": 3.0,
        "output": 15.0,
        "cache_create": 3.75,
        "cache_read": 0.30,
    },
    "claude-sonnet-4-20250514": {
        "input": 3.0,
        "output": 15.0,
        "cache_create": 3.75,
        "cache_read": 0.30,
    },
    "claude-haiku-4-5-20250514": {
        "input": 1.0,
        "output": 5.0,
        "cache_create": 1.25,
        "cache_read": 0.10,
    },
    # Claude 3.x models
    "claude-3-5-sonnet-20241022": {
        "input": 3.0,
        "output": 15.0,
        "cache_create": 3.75,
        "cache_read": 0.30,
    },
    "claude-3-5-haiku-20241022": {
        "input": 0.80,
        "output": 4.0,
        "cache_create": 1.0,
        "cache_read": 0.08,
    },
    "claude-3-opus-20240229": {
        "input": 15.0,
        "output": 75.0,
        "cache_create": 18.75,
        "cache_read": 1.50,
    },
    "claude-3-haiku-20240307": {
        "input": 0.25,
        "output": 1.25,
        "cache_create": 0.30,
        "cache_read": 0.03,
    },
}

# Default pricing for unknown models
DEFAULT_PRICING = PRICING["claude-sonnet-4-20250514"]


def get_model_pricing(model: str) -> dict[str, float]:
    """Get pricing for a model, with fallback to default."""
    return PRICING.get(model, DEFAULT_PRICING)


def calculate_cost(tokens: TokenUsage, model: str | None = None) -> CostBreakdown:
    """Calculate cost breakdown from token usage."""
    pricing = get_model_pricing(model) if model else DEFAULT_PRICING

    return CostBreakdown(
        input_cost=tokens.input_tokens * pricing["input"] / 1_000_000,
        output_cost=tokens.output_tokens * pricing["output"] / 1_000_000,
        cache_creation_cost=tokens.cache_creation_input_tokens
        * pricing["cache_create"]
        / 1_000_000,
        cache_read_cost=tokens.cache_read_input_tokens * pricing["cache_read"] / 1_000_000,
    )


def calculate_cost_from_raw(
    input_tokens: int,
    output_tokens: int,
    cache_creation: int = 0,
    cache_read: int = 0,
    model: str | None = None,
) -> float:
    """Calculate total cost from raw token counts."""
    pricing = get_model_pricing(model) if model else DEFAULT_PRICING

    return (
        input_tokens * pricing["input"] / 1_000_000
        + output_tokens * pricing["output"] / 1_000_000
        + cache_creation * pricing["cache_create"] / 1_000_000
        + cache_read * pricing["cache_read"] / 1_000_000
    )


def count_lines_changed(old_string: str | None, new_string: str | None) -> tuple[int, int]:
    """Count lines added and removed from an edit operation.

    Returns:
        Tuple of (lines_added, lines_removed)
    """
    old_lines = old_string.count("\n") + 1 if old_string else 0
    new_lines = new_string.count("\n") + 1 if new_string else 0

    diff = new_lines - old_lines
    return (max(0, diff), max(0, -diff))


def calculate_cache_hit_rate(cache_read: int, cache_creation: int, input_tokens: int) -> float:
    """Calculate cache hit rate percentage."""
    total_cacheable = cache_read + cache_creation + input_tokens
    if total_cacheable == 0:
        return 0.0
    return (cache_read / total_cacheable) * 100


def format_cost(cost: float) -> str:
    """Format cost for display."""
    if cost < 0.01:
        precision = 4
    elif cost < 1:
        precision = 3
    else:
        precision = 2
    return f"${cost:.{precision}f}"

"""Metrics computation service with dynamic pricing from LiteLLM."""

import httpx
from loguru import logger

from ..models.entries import TokenUsage
from ..models.responses import CostBreakdown

LITELLM_PRICING_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)

# Fallback pricing per million tokens (used if LiteLLM fetch fails)
FALLBACK_PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {
        "input": 3.0,
        "output": 15.0,
        "cache_create": 3.75,
        "cache_read": 0.30,
    },
}

# Global pricing cache (populated on startup)
_pricing_cache: dict[str, dict[str, float]] = {}


def _convert_litellm_pricing(model_data: dict) -> dict[str, float] | None:
    """Convert LiteLLM pricing format to our format (per million tokens)."""
    input_cost = model_data.get("input_cost_per_token")
    output_cost = model_data.get("output_cost_per_token")

    if input_cost is None or output_cost is None:
        return None

    # LiteLLM stores cost per token, we want per million tokens (rounded to 2 decimals)
    cache_create = model_data.get("cache_creation_input_token_cost", input_cost * 1.25)
    cache_read = model_data.get("cache_read_input_token_cost", input_cost * 0.1)

    return {
        "input": round(input_cost * 1_000_000, 2),
        "output": round(output_cost * 1_000_000, 2),
        "cache_create": round(cache_create * 1_000_000, 2),
        "cache_read": round(cache_read * 1_000_000, 2),
    }


def _extract_claude_pricing(litellm_data: dict) -> dict[str, dict[str, float]]:
    """Extract Claude model pricing from LiteLLM data."""
    pricing = {}

    # Model name mappings: LiteLLM key patterns -> our normalized names
    claude_patterns = [
        # Direct Anthropic API models (claude/ prefix)
        ("claude/claude-", "claude-"),
        # Also check for models without prefix
        ("claude-opus", "claude-opus"),
        ("claude-sonnet", "claude-sonnet"),
        ("claude-haiku", "claude-haiku"),
        ("claude-3", "claude-3"),
    ]

    for litellm_key, model_data in litellm_data.items():
        if not isinstance(model_data, dict):
            continue

        # Check if this is a Claude model
        normalized_key = None

        # Prefer claude/ prefixed models (direct Anthropic API)
        if litellm_key.startswith("claude/"):
            normalized_key = litellm_key.replace("claude/", "")
        # Skip AWS Bedrock and Vertex models for now (they have different pricing)
        elif litellm_key.startswith(("anthropic.", "bedrock/", "vertex_ai/")):
            continue
        # Check for direct claude model names
        elif any(litellm_key.startswith(pattern) for pattern, _ in claude_patterns[1:]):
            normalized_key = litellm_key

        if normalized_key:
            converted = _convert_litellm_pricing(model_data)
            if converted:
                pricing[normalized_key] = converted

    return pricing


def load_pricing_from_litellm() -> dict[str, dict[str, float]]:
    """Fetch and parse pricing data from LiteLLM GitHub repository."""
    logger.info("Pulling pricing data from LiteLLM: {}", LITELLM_PRICING_URL)

    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(LITELLM_PRICING_URL)
            response.raise_for_status()
            litellm_data = response.json()

        pricing = _extract_claude_pricing(litellm_data)

        if pricing:
            logger.info("Loaded pricing for {} Claude models from LiteLLM", len(pricing))
            # Log a few example models
            for model in list(pricing.keys())[:3]:
                p = pricing[model]
                logger.debug(
                    "  {} - input: ${}/MTok, output: ${}/MTok",
                    model,
                    p["input"],
                    p["output"],
                )
            return pricing
        else:
            logger.warning("No Claude models found in LiteLLM data, using fallback pricing")
            return FALLBACK_PRICING

    except httpx.HTTPError as e:
        logger.error("Failed to fetch LiteLLM pricing (HTTP error): {}", e)
        return FALLBACK_PRICING
    except Exception as e:
        logger.error("Failed to parse LiteLLM pricing: {}", e)
        return FALLBACK_PRICING


def init_pricing() -> None:
    """Initialize pricing cache. Call this on server startup."""
    global _pricing_cache
    _pricing_cache = load_pricing_from_litellm()


def get_pricing() -> dict[str, dict[str, float]]:
    """Get the current pricing cache."""
    if not _pricing_cache:
        init_pricing()
    return _pricing_cache


def get_model_pricing(model: str | None) -> dict[str, float]:
    """Get pricing for a model, with fallback to default."""
    if not model:
        return FALLBACK_PRICING["claude-sonnet-4-20250514"]

    pricing = get_pricing()

    # Try exact match first
    if model in pricing:
        return pricing[model]

    # Try partial matches (model name might have different date suffix)
    model_base = model.rsplit("-", 1)[0] if "-" in model else model
    for key in pricing:
        if key.startswith(model_base):
            return pricing[key]

    # Fallback to sonnet pricing
    logger.debug("No pricing found for model '{}', using default", model)
    return FALLBACK_PRICING["claude-sonnet-4-20250514"]


def calculate_cost(tokens: TokenUsage, model: str | None = None) -> CostBreakdown:
    """Calculate cost breakdown from token usage."""
    pricing = get_model_pricing(model)

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
    pricing = get_model_pricing(model)

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

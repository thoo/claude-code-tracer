"""Metrics-related API endpoints."""

from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from ..models.responses import DailyMetrics, DailyMetricsResponse
from ..services.database import get_connection, get_project_dir, list_projects, list_sessions
from ..services.log_parser import get_project_total_metrics
from ..services.metrics import calculate_cost_from_raw
from ..services.metrics import get_pricing as get_model_pricing
from ..services.queries import DAILY_METRICS_QUERY

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/pricing")
async def get_pricing_endpoint() -> dict[str, dict[str, float]]:
    """Get current model pricing (dynamically loaded from LiteLLM)."""
    return get_model_pricing()


@router.get("/daily/{project_hash}", response_model=DailyMetricsResponse)
async def get_daily_metrics(
    project_hash: str,
    start_date: str | None = Query(default=None),
    end_date: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=365),
) -> DailyMetricsResponse:
    """Get daily aggregated metrics for a project."""
    project_dir = get_project_dir(project_hash)
    if not project_dir.exists():
        return DailyMetricsResponse(metrics=[])

    end_dt = datetime.fromisoformat(end_date) if end_date else datetime.now()
    start_dt = datetime.fromisoformat(start_date) if start_date else end_dt - timedelta(days=days)

    sessions = list_sessions(project_hash)
    if not sessions:
        return DailyMetricsResponse(metrics=[])

    daily_data = _aggregate_daily_metrics(project_dir, sessions, start_dt, end_dt)
    metrics = _convert_daily_data_to_response(daily_data)

    return DailyMetricsResponse(metrics=metrics)


def _aggregate_daily_metrics(
    project_dir, sessions: list[dict], start_dt: datetime, end_dt: datetime
) -> dict[str, dict[str, int]]:
    """Aggregate daily metrics across all sessions."""
    daily_data: dict[str, dict[str, int]] = {}

    with get_connection() as conn:
        for sess in sessions:
            session_path = project_dir / f"{sess['session_id']}.jsonl"
            if not session_path.exists():
                continue

            try:
                result = conn.execute(
                    DAILY_METRICS_QUERY.format(
                        path=str(session_path),
                        start_date=start_dt.isoformat(),
                        end_date=end_dt.isoformat(),
                    )
                ).fetchall()

                for row in result:
                    if not row[0]:
                        continue
                    date_key = row[0].strftime("%Y-%m-%d")

                    if date_key not in daily_data:
                        daily_data[date_key] = {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cache_creation": 0,
                            "cache_read": 0,
                            "message_count": 0,
                        }

                    daily_data[date_key]["input_tokens"] += row[1] or 0
                    daily_data[date_key]["output_tokens"] += row[2] or 0
                    daily_data[date_key]["cache_creation"] += row[3] or 0
                    daily_data[date_key]["cache_read"] += row[4] or 0
                    daily_data[date_key]["message_count"] += row[5] or 0
            except Exception:
                continue

    return daily_data


def _convert_daily_data_to_response(daily_data: dict[str, dict[str, int]]) -> list[DailyMetrics]:
    """Convert aggregated daily data to DailyMetrics response objects."""
    return [
        DailyMetrics(
            date=datetime.fromisoformat(date_str),
            input_tokens=data["input_tokens"],
            output_tokens=data["output_tokens"],
            cache_creation=data["cache_creation"],
            cache_read=data["cache_read"],
            message_count=data["message_count"],
            cost=calculate_cost_from_raw(
                data["input_tokens"],
                data["output_tokens"],
                data["cache_creation"],
                data["cache_read"],
            ),
        )
        for date_str, data in sorted(daily_data.items())
    ]


@router.get("/aggregate")
async def get_aggregate_metrics(
    project_hash: str | None = Query(default=None),
) -> dict:
    """Get aggregated metrics across all or a specific project."""
    if project_hash:
        return _format_project_metrics(get_project_total_metrics(project_hash))

    projects = list_projects()
    input_tokens = 0
    output_tokens = 0
    cache_creation = 0
    cache_read = 0
    total_cost = 0.0
    total_sessions = 0
    first_activity = None
    last_activity = None

    for proj in projects:
        metrics = get_project_total_metrics(str(proj["path_hash"]))
        tokens = metrics.get("tokens", {})
        input_tokens += tokens.get("input_tokens", 0)
        output_tokens += tokens.get("output_tokens", 0)
        cache_creation += tokens.get("cache_creation_input_tokens", 0)
        cache_read += tokens.get("cache_read_input_tokens", 0)
        total_cost += metrics.get("total_cost", 0.0)
        total_sessions += metrics.get("session_count", 0)

        proj_first = metrics.get("first_activity")
        proj_last = metrics.get("last_activity")

        if proj_first and (first_activity is None or proj_first < first_activity):
            first_activity = proj_first
        if proj_last and (last_activity is None or proj_last > last_activity):
            last_activity = proj_last

    return {
        "tokens": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
        },
        "total_cost": total_cost,
        "session_count": total_sessions,
        "project_count": len(projects),
        "first_activity": first_activity.isoformat() if first_activity else None,
        "last_activity": last_activity.isoformat() if last_activity else None,
    }


def _format_project_metrics(metrics: dict) -> dict:
    """Format project metrics for API response."""
    tokens = metrics.get("tokens", {})
    first_activity = metrics.get("first_activity")
    last_activity = metrics.get("last_activity")
    return {
        "tokens": tokens,
        "total_cost": metrics.get("total_cost", 0.0),
        "session_count": metrics.get("session_count", 0),
        "first_activity": first_activity.isoformat() if first_activity else None,
        "last_activity": last_activity.isoformat() if last_activity else None,
    }

"""Background task stubs for long-running route optimization and AI analysis jobs."""

from app.workers.celery_app import celery_app


@celery_app.task(name="optimize_routes_task")
def optimize_routes_task(route_request_id: str) -> None:
    """Run route optimization asynchronously and persist the result."""
    raise NotImplementedError


@celery_app.task(name="analyze_delivery_list_task")
def analyze_delivery_list_task(import_batch_id: str) -> None:
    """Run LLM-based delivery list analysis asynchronously."""
    raise NotImplementedError

"""Celery application instance, configured with Redis as broker and backend."""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "ai_delivery_planner",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.autodiscover_tasks(["app.workers"])

# TODO: no periodic (celery beat) tasks exist yet — everything currently
# runs either synchronously in-request or as an on-demand task. Add a
# `beat_schedule` here (and a beat service in infra's docker-compose) once
# a real recurring job is needed (e.g. cleaning up stale routes).

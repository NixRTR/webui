"""
Notification evaluator worker
Periodically evaluates notification rules and sends alerts when thresholds are exceeded
"""
import asyncio
import logging
from ..celery_app import app
from ..database import with_worker_session_factory
from ..collectors.notifications import NotificationEvaluator

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name='backend.workers.notifications.evaluate_notifications',
    max_retries=3,
    default_retry_delay=60,  # Retry after 1 minute on failure
)
def evaluate_notifications_task(self):
    """Celery task wrapper for notification evaluation
    
    This task evaluates all enabled notification rules and sends alerts.
    Scheduled every 30 seconds via Celery Beat.
    Uses a fresh async engine/session per run to avoid 'Future attached to a different loop' after fork.
    """
    try:
        logger.debug("Starting notification evaluation task...")

        async def _run(session_factory):
            evaluator = NotificationEvaluator(session_factory)
            await evaluator.evaluate_all()

        asyncio.run(with_worker_session_factory(_run))
        logger.debug("Notification evaluation task completed successfully")
    except Exception as exc:
        logger.error(
            "Notification evaluator error: %s", exc, exc_info=True
        )
        # Retry the task
        raise self.retry(exc=exc)

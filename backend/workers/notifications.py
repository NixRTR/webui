"""
Notification evaluator worker
Periodically evaluates notification rules and sends alerts when thresholds are exceeded
"""
import asyncio
import logging
from ..celery_app import app
from ..database import AsyncSessionLocal
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
    """
    try:
        logger.debug("Starting notification evaluation task...")
        # Create evaluator and run evaluation
        evaluator = NotificationEvaluator(AsyncSessionLocal)
        asyncio.run(evaluator.evaluate_all())
        logger.debug("Notification evaluation task completed successfully")
    except Exception as exc:
        logger.error(
            "Notification evaluator error: %s", exc, exc_info=True
        )
        # Retry the task
        raise self.retry(exc=exc)

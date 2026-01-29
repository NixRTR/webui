"""
Daily aggregation worker
Runs data aggregation jobs daily at 2 AM UTC to reduce storage usage
"""
import asyncio
import logging
from ..celery_app import app
from ..collectors.aggregation import run_aggregation_job

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name='backend.workers.aggregation.run_aggregation_job',
    max_retries=3,
    default_retry_delay=3600,  # Retry after 1 hour on failure
)
def run_aggregation_job_task(self):
    """Celery task wrapper for aggregation job
    
    This task runs the async aggregation job in an event loop.
    Scheduled daily at 2 AM UTC via Celery Beat.
    """
    try:
        logger.info("Starting aggregation job task...")
        from ..database import with_worker_session_factory
        async def _run(session_factory):
            await run_aggregation_job(session_factory)
        asyncio.run(with_worker_session_factory(_run))
        logger.info("Aggregation job task completed successfully")
    except Exception as exc:
        logger.error(f"Error in aggregation job task: {exc}", exc_info=True)
        # Retry the task
        raise self.retry(exc=exc)

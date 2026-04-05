"""
Periodic VACUUM ANALYZE for metric tables (runs via psql, autocommit).
"""
import logging

from ..celery_app import app
from ..utils.pg_vacuum import vacuum_analyze_metric_tables

logger = logging.getLogger(__name__)


@app.task(
    bind=True,
    name="backend.workers.vacuum_metrics.vacuum_metric_tables_task",
    max_retries=2,
    default_retry_delay=600,
)
def vacuum_metric_tables_task(self):
    try:
        logger.info("Starting VACUUM ANALYZE metric tables task...")
        vacuum_analyze_metric_tables()
        logger.info("VACUUM ANALYZE metric tables task completed")
    except Exception as exc:
        logger.error("VACUUM ANALYZE task failed: %s", exc, exc_info=True)
        raise self.retry(exc=exc)

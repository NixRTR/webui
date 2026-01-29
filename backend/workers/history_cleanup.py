"""
History cleanup worker
Runs periodic cleanup of DNS and DHCP configuration history based on retention policy
Retention: Keep at minimum the last 10 changes, plus all changes within 90 days
"""
import asyncio
import logging
from sqlalchemy import text
from ..celery_app import app
from ..database import with_worker_session_factory

logger = logging.getLogger(__name__)


async def cleanup_history(session_factory):
    """Clean up DNS and DHCP configuration history based on retention policy"""
    async with session_factory() as session:
        try:
            # Call the cleanup functions from the migration
            result_dns = await session.execute(text("SELECT cleanup_dns_config_history()"))
            dns_deleted = result_dns.scalar()
            
            result_dhcp = await session.execute(text("SELECT cleanup_dhcp_config_history()"))
            dhcp_deleted = result_dhcp.scalar()
            
            await session.commit()
            
            logger.info(f"History cleanup completed: DNS={dns_deleted} records deleted, DHCP={dhcp_deleted} records deleted")
        except Exception as e:
            logger.error(f"Error during history cleanup: {e}", exc_info=True)
            await session.rollback()
            raise


@app.task(
    bind=True,
    name='backend.workers.history_cleanup.cleanup_history',
    max_retries=3,
    default_retry_delay=3600,  # Retry after 1 hour on failure
)
def cleanup_history_task(self):
    """Celery task wrapper for history cleanup
    
    This task runs the async history cleanup job in an event loop.
    Scheduled daily at 3 AM UTC via Celery Beat.
    Uses a fresh async engine/session per run to avoid 'Future attached to a different loop' after fork.
    """
    try:
        logger.info("Starting history cleanup task...")
        asyncio.run(with_worker_session_factory(cleanup_history))
        logger.info("History cleanup task completed successfully")
    except Exception as exc:
        logger.error(f"Error in history cleanup task: {exc}", exc_info=True)
        # Retry the task
        raise self.retry(exc=exc)

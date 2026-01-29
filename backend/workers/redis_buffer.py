"""
Redis write buffer flush worker
Reads metrics from Redis buffers and writes them to PostgreSQL in batches
"""
import asyncio
import json
import logging
from typing import Any
from sqlalchemy import insert
from ..celery_app import app
from ..database import (
    with_worker_session_factory,
    SystemMetricsDB,
    InterfaceStatsDB,
    ServiceStatusDB,
    DiskIOMetricsDB,
    TemperatureMetricsDB,
    ClientBandwidthStatsDB,
    ClientConnectionStatsDB,
    DHCPLeaseDB,
)
from ..utils.redis_client import (
    list_length, list_pop, is_redis_available
)
from ..config import settings

logger = logging.getLogger(__name__)


async def _flush_all_buffers(session_factory):
    """Flush all metric buffers to PostgreSQL"""
    if not is_redis_available():
        logger.debug("Redis not available, skipping buffer flush")
        return
    
    buffers = [
        ("metrics:buffer:system", SystemMetricsDB),
        ("metrics:buffer:interfaces", InterfaceStatsDB),
        ("metrics:buffer:services", ServiceStatusDB),
        ("metrics:buffer:disk_io", DiskIOMetricsDB),
        ("metrics:buffer:temperatures", TemperatureMetricsDB),
        ("metrics:buffer:bandwidth", ClientBandwidthStatsDB),
        ("metrics:buffer:connections", ClientConnectionStatsDB),
        ("metrics:buffer:dhcp_leases", DHCPLeaseDB),
    ]
    
    for buffer_key, model_class in buffers:
        try:
            buffer_size = await list_length(buffer_key)
            if buffer_size == 0:
                continue
            
            # Flush up to max_size items at a time
            items_to_flush = min(buffer_size, settings.redis_buffer_max_size)
            if items_to_flush > 0:
                await _flush_buffer(buffer_key, model_class, items_to_flush, session_factory)
        except Exception as e:
            logger.error(f"Error flushing buffer {buffer_key}: {e}", exc_info=True)


async def _flush_buffer(buffer_key: str, model_class: Any, count: int, session_factory):
    """Flush a specific buffer to PostgreSQL"""
    # Pop items from Redis list
    items_json = await list_pop(buffer_key, count)
    
    if not items_json:
        return
    
    # Parse JSON items
    items = []
    for item_json in items_json:
        try:
            item = json.loads(item_json)
            items.append(item)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse buffer item from {buffer_key}: {e}")
            continue
    
    if not items:
        return
    
    # Write to PostgreSQL using bulk insert
    async with session_factory() as session:
        try:
            await session.execute(
                insert(model_class).values(items)
            )
            await session.commit()
            logger.debug(f"Flushed {len(items)} items from {buffer_key} to PostgreSQL")
        except Exception as e:
            logger.error(f"Failed to flush buffer {buffer_key} to PostgreSQL: {e}", exc_info=True)
            await session.rollback()


@app.task(
    bind=True,
    name='backend.workers.redis_buffer.flush_buffers',
    max_retries=3,
    default_retry_delay=30,  # Retry after 30 seconds on failure
)
def flush_buffers_task(self):
    """Celery task wrapper for Redis buffer flushing
    
    This task flushes metrics from Redis buffers to PostgreSQL.
    Scheduled every 5 seconds via Celery Beat (if enabled).
    Uses a fresh async engine/session per run to avoid 'Future attached to a different loop' after fork.
    """
    try:
        logger.debug("Starting Redis buffer flush task...")
        asyncio.run(with_worker_session_factory(_flush_all_buffers))
        logger.debug("Redis buffer flush task completed successfully")
    except Exception as exc:
        logger.error(f"Error in buffer flush task: {exc}", exc_info=True)
        # Retry the task
        raise self.retry(exc=exc)

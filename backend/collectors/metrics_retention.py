"""
Prune high-volume time-series tables and optional emergency DB size trim.
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..database import (
    AsyncSessionLocal,
    SystemMetricsDB,
    InterfaceStatsDB,
    DiskIOMetricsDB,
    TemperatureMetricsDB,
    ServiceStatusDB,
    CakeStatsDB,
    SpeedtestResultDB,
    ClientBandwidthStatsDB,
    ClientConnectionStatsDB,
)

logger = logging.getLogger(__name__)

_TIME_SERIES_MODELS: list[Any] = [
    SystemMetricsDB,
    InterfaceStatsDB,
    DiskIOMetricsDB,
    TemperatureMetricsDB,
    ServiceStatusDB,
    CakeStatsDB,
    SpeedtestResultDB,
]


async def _batched_delete_before(
    session: AsyncSession,
    model: Any,
    cutoff: datetime,
    batch_size: int,
) -> int:
    """Delete up to batch_size rows with timestamp < cutoff per iteration; repeat until none."""
    total = 0
    while True:
        subq = (
            select(model.id)
            .where(model.timestamp < cutoff)
            .order_by(model.timestamp.asc())
            .limit(batch_size)
        )
        result = await session.execute(delete(model).where(model.id.in_(subq)))
        await session.commit()
        n = result.rowcount or 0
        total += n
        if n == 0:
            break
    return total


async def prune_time_series_metrics(session_factory: Any = None) -> None:
    """Delete old rows from per-tick metrics tables (not bandwidth/connection — those use aggregation)."""
    sf = session_factory or AsyncSessionLocal
    cutoff = datetime.now(timezone.utc) - timedelta(days=settings.metrics_retention_days)
    batch = min(settings.metrics_emergency_delete_batch_size, 50_000)

    async with sf() as session:
        for model in _TIME_SERIES_MODELS:
            name = getattr(model, "__tablename__", str(model))
            try:
                n = await _batched_delete_before(session, model, cutoff, batch)
                if n:
                    logger.info("metrics retention: removed %s rows from %s", n, name)
            except Exception as e:
                logger.error("metrics retention failed for %s: %s", name, e, exc_info=True)
                raise


async def _database_size_bytes(session: AsyncSession) -> int:
    r = await session.execute(text("SELECT pg_database_size(current_database())"))
    return int(r.scalar_one())


# Coarse aggregates first (fewer rows, less detail loss per MiB) then finer levels.
_EMERGENCY_AGG_LEVEL_ORDER = ("1d", "1h", "5m", "1m", "raw")


async def _emergency_delete_batch_below_floor(
    session: AsyncSession,
    model: Any,
    floor_ts: datetime,
    batch_size: int,
    agg_level: str | None,
) -> int:
    """Delete up to batch_size oldest rows with timestamp < floor_ts; optionally filter aggregation_level."""
    q = select(model.id).where(model.timestamp < floor_ts)
    if agg_level is not None:
        q = q.where(model.aggregation_level == agg_level)
    subq = q.order_by(model.timestamp.asc()).limit(batch_size)
    result = await session.execute(delete(model).where(model.id.in_(subq)))
    await session.commit()
    return result.rowcount or 0


async def emergency_trim_database(session_factory: Any = None) -> None:
    """
    If metrics_max_database_gb > 0, delete oldest bandwidth/connection rows below the emergency floor
    until DB size is under target or no progress. Prefers 1d, then 1h, then finer aggregation levels.
    """
    if settings.metrics_max_database_gb <= 0:
        return

    target = int(settings.metrics_max_database_gb * (1024**3))
    floor_ts = datetime.now(timezone.utc) - timedelta(days=settings.metrics_emergency_min_retention_days)
    batch = settings.metrics_emergency_delete_batch_size
    max_batches = settings.metrics_emergency_max_batches

    sf = session_factory or AsyncSessionLocal
    async with sf() as session:
        for batch_idx in range(max_batches):
            try:
                sz = await _database_size_bytes(session)
            except Exception as e:
                logger.error("emergency trim: could not read database size: %s", e, exc_info=True)
                return

            if sz <= target:
                logger.info("emergency trim: database size %s <= target %s bytes", sz, target)
                return

            deleted_total = 0
            for level in _EMERGENCY_AGG_LEVEL_ORDER:
                for model in (ClientConnectionStatsDB, ClientBandwidthStatsDB):
                    n = await _emergency_delete_batch_below_floor(
                        session, model, floor_ts, batch, level
                    )
                    if n:
                        deleted_total += n
                        break
                if deleted_total:
                    break

            if deleted_total == 0:
                for model in (ClientConnectionStatsDB, ClientBandwidthStatsDB):
                    n = await _emergency_delete_batch_below_floor(
                        session, model, floor_ts, batch, None
                    )
                    deleted_total += n

            logger.warning(
                "emergency trim: batch %s deleted %s rows (db_size=%s target=%s)",
                batch_idx + 1,
                deleted_total,
                sz,
                target,
            )
            if deleted_total == 0:
                logger.warning("emergency trim: no rows left below floor; stopping")
                return

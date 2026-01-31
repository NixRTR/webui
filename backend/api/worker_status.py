"""
Worker status API - Celery queue inspection and control
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..auth import get_current_user
from ..celery_app import app
from ..config import settings
from ..utils.redis_client import get_redis_client, get_json, set_json
from ..workers.test_task import run_test_task

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/worker-status", tags=["worker-status"])

# Celery queue names (default + from task_routes)
WORKER_QUEUES = ["celery", "sequential", "parallel", "aggregation"]

INSPECT_TIMEOUT = 5


def _inspect_sync(method: str):
    """Run Celery inspect method synchronously (in thread)."""
    inspect = app.control.inspect(timeout=INSPECT_TIMEOUT)
    fn = getattr(inspect, method, None)
    if not fn:
        return None
    try:
        return fn()
    except Exception as e:
        logger.warning("Celery inspect %s failed: %s", method, e)
        return None


def _revoke_sync(task_id: str, terminate: bool = True) -> None:
    """Revoke a task (sync)."""
    app.control.revoke(task_id, terminate=terminate)


def _trigger_test_task_sync() -> str:
    """Trigger test task and return task_id (sync)."""
    result = run_test_task.delay()
    return result.id


class TaskInfo(BaseModel):
    """Normalized task info for API response."""
    id: str
    name: str
    worker: Optional[str] = None
    args: List[Any] = []
    kwargs: Dict[str, Any] = {}
    time_started: Optional[float] = None
    runtime: Optional[float] = None
    eta: Optional[str] = None
    delivery_info: Optional[Dict[str, Any]] = None


class QueueStats(BaseModel):
    """Queue statistics."""
    name: str
    broker_length: int
    reserved_count: int = 0
    active_count: int = 0


class WorkerStatusResponse(BaseModel):
    """Full worker status response."""
    queues: List[QueueStats]
    active_tasks: List[TaskInfo]
    reserved_tasks: List[TaskInfo]
    scheduled_tasks: List[TaskInfo]
    overdue_tasks: List[TaskInfo]
    long_running_tasks: List[TaskInfo]


def _normalize_tasks(worker_tasks: Optional[Dict[str, List[Dict]]]) -> List[TaskInfo]:
    """Flatten worker -> tasks dict into list of TaskInfo with worker field."""
    if not worker_tasks:
        return []
    out: List[TaskInfo] = []
    for worker_name, tasks in worker_tasks.items():
        for t in tasks or []:
            task_id = t.get("id")
            if not task_id:
                continue
            time_started = t.get("time_started")
            eta_raw = t.get("eta")
            eta_str = None
            if eta_raw is not None:
                if isinstance(eta_raw, str):
                    eta_str = eta_raw
                else:
                    try:
                        eta_str = str(eta_raw)
                    except Exception:
                        eta_str = None
            runtime = t.get("runtime")
            out.append(
                TaskInfo(
                    id=task_id,
                    name=t.get("name") or "unknown",
                    worker=worker_name,
                    args=t.get("args") or [],
                    kwargs=t.get("kwargs") or {},
                    time_started=time_started,
                    runtime=runtime,
                    eta=eta_str,
                    delivery_info=t.get("delivery_info"),
                )
            )
    return out


def _parse_eta(eta_str: Optional[str]) -> Optional[datetime]:
    """Parse ETA string to datetime (UTC)."""
    if not eta_str:
        return None
    try:
        # ISO format
        if "T" in eta_str or "-" in eta_str:
            return datetime.fromisoformat(eta_str.replace("Z", "+00:00"))
        # Unix timestamp
        ts = float(eta_str)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception:
        return None


@router.get("", response_model=WorkerStatusResponse)
async def get_worker_status(_: str = Depends(get_current_user)):
    """Return queue stats, active, reserved, scheduled, overdue, and long-running tasks."""
    cache_key = "api:worker_status"
    cached = await get_json(cache_key)
    if cached:
        return WorkerStatusResponse.model_validate(cached)

    # Queue lengths from Redis (async)
    queue_lengths: Dict[str, int] = {}
    client = await get_redis_client()
    if client:
        for q in WORKER_QUEUES:
            try:
                queue_lengths[q] = await client.llen(q)
            except Exception as e:
                logger.warning("Redis LLEN %s failed: %s", q, e)
                queue_lengths[q] = 0
    else:
        for q in WORKER_QUEUES:
            queue_lengths[q] = 0

    # Celery inspect (sync - run in thread)
    active_raw = await asyncio.to_thread(_inspect_sync, "active")
    reserved_raw = await asyncio.to_thread(_inspect_sync, "reserved")
    scheduled_raw = await asyncio.to_thread(_inspect_sync, "scheduled")

    active_tasks = _normalize_tasks(active_raw)
    reserved_tasks = _normalize_tasks(reserved_raw)
    scheduled_tasks = _normalize_tasks(scheduled_raw)

    # Count reserved/active per queue (from delivery_info if present)
    def count_by_queue(tasks: List[TaskInfo]) -> Dict[str, int]:
        counts: Dict[str, int] = {q: 0 for q in WORKER_QUEUES}
        for t in tasks:
            queue_name = "celery"
            if t.delivery_info and "routing_key" in t.delivery_info:
                queue_name = t.delivery_info["routing_key"]
            counts[queue_name] = counts.get(queue_name, 0) + 1
        return counts

    active_by_queue = count_by_queue(active_tasks)
    reserved_by_queue = count_by_queue(reserved_tasks)

    queues = [
        QueueStats(
            name=q,
            broker_length=queue_lengths.get(q, 0),
            reserved_count=reserved_by_queue.get(q, 0),
            active_count=active_by_queue.get(q, 0),
        )
        for q in WORKER_QUEUES
    ]

    # Overdue: scheduled tasks whose ETA is in the past
    now = datetime.now(timezone.utc)
    overdue_tasks: List[TaskInfo] = []
    for t in scheduled_tasks:
        eta_dt = _parse_eta(t.eta)
        if eta_dt and eta_dt < now:
            overdue_tasks.append(t)

    # Long-running: active tasks running longer than threshold
    threshold = getattr(settings, "worker_status_long_running_seconds", 300)
    long_running_tasks: List[TaskInfo] = []
    for t in active_tasks:
        runtime = t.runtime
        if runtime is not None and runtime > threshold:
            long_running_tasks.append(t)
        elif t.time_started is not None:
            # Compute runtime from time_started if runtime not in payload
            try:
                started = datetime.fromtimestamp(t.time_started, tz=timezone.utc)
                runtime_sec = (now - started).total_seconds()
                if runtime_sec > threshold:
                    long_running_tasks.append(t)
            except Exception:
                pass

    out = WorkerStatusResponse(
        queues=queues,
        active_tasks=active_tasks,
        reserved_tasks=reserved_tasks,
        scheduled_tasks=scheduled_tasks,
        overdue_tasks=overdue_tasks,
        long_running_tasks=long_running_tasks,
    )
    await set_json(cache_key, out.model_dump(mode="json"), ttl=settings.redis_cache_ttl_worker_status)
    return out


@router.post("/tasks/{task_id}/revoke", status_code=204)
async def revoke_task(
    task_id: str,
    terminate: bool = True,
    _: str = Depends(get_current_user),
):
    """Revoke (cancel) a task. If terminate=True, also terminate if already running."""
    await asyncio.to_thread(_revoke_sync, task_id, terminate=terminate)


@router.post("/queues/purge")
async def purge_queues(_: str = Depends(get_current_user)):
    """Purge all configured task queues. Irreversible."""
    client = await get_redis_client()
    if not client:
        raise HTTPException(status_code=503, detail="Redis unavailable")
    total = 0
    for q in WORKER_QUEUES:
        try:
            n = await client.llen(q)
            if n > 0:
                await client.delete(q)
                total += n
        except Exception as e:
            logger.warning("Purge queue %s failed: %s", q, e)
    return {"purged": total}


@router.post("/test-task")
async def trigger_test_task(_: str = Depends(get_current_user)):
    """Trigger the test task and return its task_id."""
    task_id = await asyncio.to_thread(_trigger_test_task_sync)
    return {"task_id": task_id}

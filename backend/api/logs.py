"""
Logs API - stream systemd journal logs for configured services
"""
import asyncio
import logging
import shutil
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, PlainTextResponse

from ..auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])

# Service ID -> systemd unit name (None = full journal)
LOG_SERVICES: dict[str, str | None] = {
    "system": None,
    "dnsmasq-lan": "dnsmasq-lan.service",
    "dnsmasq-homelab": "dnsmasq-homelab.service",
    "nginx": "nginx.service",
    "router-webui-backend": "router-webui-backend.service",
    "router-webui-celery-parallel": "router-webui-celery-parallel.service",
    "router-webui-celery-sequential": "router-webui-celery-sequential.service",
    "router-webui-celery-aggregation": "router-webui-celery-aggregation.service",
    "postgresql": "postgresql.service",
    "redis": "redis.service",
    "sshd": "sshd.service",
}

MAX_LINES = 2000
DEFAULT_LINES = 200

# Log level filter: minimum severity (syslog priority). "all" = no filter.
# journalctl -p: err=3 (err and more severe), warning=4, info=6, debug=7 (all).
PRIORITY_VALUES = frozenset({"all", "err", "warning", "info", "debug"})


def _build_journalctl_args(
    service_id: str, lines: int, follow: bool, priority: str | None = None
) -> list[str]:
    args = ["journalctl", "-n", str(lines), "--no-pager"]
    if follow:
        args.append("-f")
    if priority and priority != "all" and priority in PRIORITY_VALUES:
        args.extend(["-p", priority])
    unit = LOG_SERVICES.get(service_id)
    if unit:
        args.extend(["-u", unit])
    return args


@router.get("", response_class=PlainTextResponse)
async def get_logs(
    service: str = Query(..., description="Service ID (e.g. system, router-webui-backend)"),
    lines: int = Query(DEFAULT_LINES, ge=1, le=MAX_LINES, description="Number of lines"),
    follow: bool = Query(False, description="Stream new lines (live tail)"),
    priority: str = Query(
        "all",
        description="Minimum log level: all, err, warning, info, debug",
    ),
    _: str = Depends(get_current_user),
):
    """Get recent log lines for a service. Use follow=true for streaming."""
    if service not in LOG_SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service}")
    if priority not in PRIORITY_VALUES:
        raise HTTPException(status_code=400, detail=f"Invalid priority: {priority}")

    if follow:
        return StreamingResponse(
            _stream_logs(service, lines, priority),
            media_type="text/plain; charset=utf-8",
            headers={
                "X-Accel-Buffering": "no",  # Nginx: disable proxy buffering
                "Cache-Control": "no-cache",
            },
        )

    proc = await asyncio.create_subprocess_exec(
        *_build_journalctl_args(service, lines, follow=False, priority=priority),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0 and stderr:
        logger.warning("journalctl stderr: %s", stderr.decode(errors="replace"))
    return PlainTextResponse(stdout.decode("utf-8", errors="replace") if stdout else "")


async def _stream_logs(
    service_id: str, lines: int, priority: str = "all"
) -> AsyncIterator[bytes]:
    # Send a tiny first chunk so the HTTP response starts immediately and the client stops showing "Connecting..."
    yield b""

    args = _build_journalctl_args(service_id, lines, follow=True, priority=priority)
    # Use stdbuf to force line-unbuffered output so chunks reach the client immediately (if available)
    if shutil.which("stdbuf"):
        exec_args = ["stdbuf", "-oL"] + args
    else:
        exec_args = args
    proc = await asyncio.create_subprocess_exec(
        *exec_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    try:
        if proc.stdout:
            # Use smaller reads so first journal lines are sent quickly (don't wait for 4KB)
            while True:
                chunk = await proc.stdout.read(1024)
                if not chunk:
                    break
                yield chunk
    finally:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()


@router.get("/services")
async def list_log_services(_: str = Depends(get_current_user)):
    """List available log service IDs and display labels."""
    labels = {
        "system": "System Log",
        "dnsmasq-lan": "LAN DNS/DHCP",
        "dnsmasq-homelab": "HOMELAB DNS/DHCP",
        "nginx": "Nginx",
        "router-webui-backend": "WebUI Backend",
        "router-webui-celery-parallel": "Parallel Celery Worker",
        "router-webui-celery-sequential": "Sequential Celery Worker",
        "router-webui-celery-aggregation": "Aggregation Celery Worker",
        "postgresql": "Database",
        "redis": "REDIS",
        "sshd": "SSH",
    }
    return [{"id": sid, "label": labels.get(sid, sid)} for sid in LOG_SERVICES]

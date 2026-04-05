"""
Run VACUUM ANALYZE on metric tables via psql (must run outside a transaction).
"""
import logging
import os
import shutil
import subprocess
from typing import List, Optional

from sqlalchemy.engine.url import make_url

from ..config import settings

logger = logging.getLogger(__name__)

METRIC_TABLES: List[str] = [
    "system_metrics",
    "interface_stats",
    "disk_io_metrics",
    "temperature_metrics",
    "service_status",
    "cake_stats",
    "speedtest_results",
    "client_bandwidth_stats",
    "client_connection_stats",
]


def vacuum_analyze_metric_tables() -> None:
    """VACUUM ANALYZE known metric tables. No-op if disabled or psql missing."""
    if not settings.metrics_vacuum_analyze_enabled:
        logger.info("VACUUM ANALYZE skipped (metrics_vacuum_analyze_enabled=false)")
        return

    psql = settings.psql_bin or shutil.which("psql")
    if not psql:
        logger.warning("VACUUM ANALYZE skipped: psql not found (set PSQL_BIN or PATH)")
        return

    raw = settings.database_url
    if not raw or "postgresql" not in raw:
        logger.warning("VACUUM ANALYZE skipped: DATABASE_URL not set")
        return

    try:
        url = make_url(raw.replace("postgresql+asyncpg", "postgresql", 1))
    except Exception as e:
        logger.error("VACUUM ANALYZE: bad DATABASE_URL: %s", e)
        return

    host = url.host or "localhost"
    port = url.port or 5432
    user = url.username or ""
    database = url.database or ""
    password: Optional[str] = url.password

    statements = " ".join(f"VACUUM ANALYZE {t};" for t in METRIC_TABLES)
    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    cmd = [
        psql,
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        statements,
    ]
    try:
        subprocess.run(cmd, env=env, check=True, capture_output=True, text=True, timeout=7200)
        logger.info("VACUUM ANALYZE completed for %s tables", len(METRIC_TABLES))
    except subprocess.CalledProcessError as e:
        logger.error("VACUUM ANALYZE failed: %s %s", e, (e.stderr or "")[:2000])
        raise
    except subprocess.TimeoutExpired:
        logger.error("VACUUM ANALYZE timed out")
        raise

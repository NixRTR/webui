"""
Periodic port scanner worker - Scans devices every 30 minutes
"""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..celery_app import app
from ..database import AsyncSessionLocal, NetworkDeviceDB, DevicePortScanDB
from ..workers.port_scanner import queue_port_scan

logger = logging.getLogger(__name__)


@app.task(name='backend.workers.port_scanner_periodic.scan_devices_periodic')
def scan_devices_periodic():
    """Periodic task to scan online devices
    
    Checks all online devices and queues port scans if:
    - No scan exists, OR
    - Last scan was completed more than 30 minutes ago
    """
    logger.info("Starting periodic device port scan")
    
    async def _run_periodic_scan():
        async with AsyncSessionLocal() as session:
            # Get all online devices
            result = await session.execute(
                select(NetworkDeviceDB).where(
                    NetworkDeviceDB.is_online == True
                )
            )
            online_devices = result.scalars().all()
            
            logger.info(f"Found {len(online_devices)} online devices to check")
            
            # Calculate cutoff time (30 minutes ago)
            cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=30)
            
            scanned_count = 0
            skipped_count = 0
            
            for device in online_devices:
                mac_address = str(device.mac_address)
                ip_address = str(device.ip_address)
                
                # Check if there's a recent completed scan
                scan_result = await session.execute(
                    select(DevicePortScanDB).where(
                        DevicePortScanDB.mac_address == mac_address,
                        DevicePortScanDB.scan_status == 'completed'
                    ).order_by(DevicePortScanDB.scan_completed_at.desc())
                )
                last_scan = scan_result.scalar_one_or_none()
                
                # Check if scan is needed
                needs_scan = False
                if not last_scan:
                    # No scan exists
                    needs_scan = True
                    logger.debug(f"Device {mac_address} has no scan history, queuing scan")
                elif last_scan.scan_completed_at and last_scan.scan_completed_at < cutoff_time:
                    # Last scan is older than 30 minutes
                    needs_scan = True
                    logger.debug(f"Device {mac_address} last scan was {last_scan.scan_completed_at}, queuing new scan")
                elif last_scan.scan_status in ['failed']:
                    # Last scan failed, try again
                    needs_scan = True
                    logger.debug(f"Device {mac_address} last scan failed, queuing retry")
                
                if needs_scan:
                    # Check if there's already a pending/in-progress scan
                    pending_result = await session.execute(
                        select(DevicePortScanDB).where(
                            DevicePortScanDB.mac_address == mac_address,
                            DevicePortScanDB.scan_status.in_(['pending', 'in_progress'])
                        )
                    )
                    pending_scan = pending_result.scalar_one_or_none()
                    
                    if not pending_scan:
                        # Queue the scan
                        queued = await queue_port_scan(mac_address, ip_address)
                        if queued:
                            scanned_count += 1
                        else:
                            skipped_count += 1
                    else:
                        skipped_count += 1
                        logger.debug(f"Device {mac_address} already has scan {pending_scan.scan_status}, skipping")
                else:
                    skipped_count += 1
            
            logger.info(f"Periodic port scan completed: {scanned_count} scans queued, {skipped_count} skipped")
            return {
                'scanned': scanned_count,
                'skipped': skipped_count,
                'total': len(online_devices)
            }
    
    # Run async function using asyncio
    import asyncio
    return asyncio.run(_run_periodic_scan())

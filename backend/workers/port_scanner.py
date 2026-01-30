"""
Port scanner worker - Celery task for scanning device ports
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ..celery_app import app
from ..database import (
    with_worker_session_factory,
    AsyncSessionLocal,
    DevicePortScanDB,
    DevicePortScanResultDB,
    NetworkDeviceDB,
)
from ..utils.port_scanner import scan_device_ports

logger = logging.getLogger(__name__)


def _make_run_scan(mac_address: str, ip_address: str):
    """Build async scan runner (shared by scan_device_ports_task and scan_new_device_ports_task)."""
    async def _run_scan(session_factory):
        async with session_factory() as session:
            # Check if there's already an in-progress scan for this device
            result = await session.execute(
                select(DevicePortScanDB).where(
                    DevicePortScanDB.mac_address == mac_address,
                    DevicePortScanDB.scan_status.in_(['pending', 'in_progress'])
                ).order_by(DevicePortScanDB.scan_started_at.desc())
            )
            existing_scan = result.scalar_one_or_none()
            
            # If there's an in-progress scan, don't start a new one
            if existing_scan and existing_scan.scan_status == 'in_progress':
                logger.warning(f"Scan already in progress for {mac_address}, skipping")
                return {'status': 'skipped', 'reason': 'scan_already_in_progress'}
            
            # Create new scan record or update existing pending scan
            if existing_scan and existing_scan.scan_status == 'pending':
                scan_record = existing_scan
                scan_record.scan_status = 'in_progress'
                scan_record.scan_started_at = datetime.now(timezone.utc)
            else:
                scan_record = DevicePortScanDB(
                    mac_address=mac_address,
                    ip_address=ip_address,
                    scan_status='in_progress',
                    scan_started_at=datetime.now(timezone.utc)
                )
                session.add(scan_record)
            
            await session.commit()
            await session.refresh(scan_record)
            scan_id = scan_record.id
            
            try:
                # Run the actual port scan
                scan_result = scan_device_ports(ip_address, mac_address, timeout=300)
                
                # Update scan record with results
                async with session_factory() as update_session:
                    scan_record = await update_session.get(DevicePortScanDB, scan_id)
                    if not scan_record:
                        logger.error(f"Scan record {scan_id} not found after scan completion")
                        return {'status': 'error', 'error': 'scan_record_not_found'}
                    
                    if scan_result['success']:
                        # Delete old results for this scan (if any)
                        old_results = await update_session.execute(
                            select(DevicePortScanResultDB).where(
                                DevicePortScanResultDB.scan_id == scan_id
                            )
                        )
                        for old_result in old_results.scalars().all():
                            await update_session.delete(old_result)
                        
                        # Store new port scan results
                        for port_info in scan_result['ports']:
                            port_result = DevicePortScanResultDB(
                                scan_id=scan_id,
                                port=port_info['port'],
                                state=port_info['state'],
                                service_name=port_info.get('service_name'),
                                service_version=port_info.get('service_version'),
                                service_product=port_info.get('service_product'),
                                service_extrainfo=port_info.get('service_extrainfo'),
                                protocol=port_info.get('protocol', 'tcp')
                            )
                            update_session.add(port_result)
                        
                        scan_record.scan_status = 'completed'
                        scan_record.scan_completed_at = datetime.now(timezone.utc)
                        scan_record.error_message = None
                        
                        logger.info(f"Port scan completed successfully for {mac_address}: found {len(scan_result['ports'])} ports")
                    else:
                        # Scan failed
                        scan_record.scan_status = 'failed'
                        scan_record.scan_completed_at = datetime.now(timezone.utc)
                        scan_record.error_message = scan_result.get('error', 'Unknown error')
                        
                        logger.error(f"Port scan failed for {mac_address}: {scan_record.error_message}")
                    
                    await update_session.commit()
                    
                    return {
                        'status': 'completed' if scan_result['success'] else 'failed',
                        'ports_count': len(scan_result['ports']) if scan_result['success'] else 0,
                        'error': scan_result.get('error')
                    }
                    
            except Exception as e:
                logger.error(f"Exception during port scan for {mac_address}: {e}", exc_info=True)
                
                # Update scan record with error
                async with session_factory() as error_session:
                    scan_record = await error_session.get(DevicePortScanDB, scan_id)
                    if scan_record:
                        scan_record.scan_status = 'failed'
                        scan_record.scan_completed_at = datetime.now(timezone.utc)
                        scan_record.error_message = str(e)
                        await error_session.commit()
                
                return {'status': 'error', 'error': str(e)}

    return _run_scan


@app.task(name='backend.workers.port_scanner.scan_device_ports_task', bind=True)
def scan_device_ports_task(self, mac_address: str, ip_address: str):
    """Celery task to scan device ports using nmap
    
    Args:
        mac_address: Device MAC address
        ip_address: Device IP address to scan
    
    Returns:
        dict with scan results
    """
    logger.info(f"Starting port scan task for device {mac_address} at {ip_address}")
    return _run_port_scan(mac_address, ip_address)


@app.task(name='backend.workers.port_scanner.scan_new_device_ports', bind=True)
def scan_new_device_ports_task(self, mac_address: str, ip_address: str):
    """Celery task to scan newly discovered device ports (sequential processing)
    
    This task is routed to the 'new_device_scans' queue which processes one device at a time.
    
    Args:
        mac_address: Device MAC address
        ip_address: Device IP address to scan
    
    Returns:
        dict with scan results
    """
    logger.info(f"Starting NEW device port scan for {mac_address} at {ip_address}")
    return _run_port_scan(mac_address, ip_address)


def _run_port_scan(mac_address: str, ip_address: str):
    """Execute port scan with fresh worker session (shared by both scan tasks)."""
    import asyncio
    return asyncio.run(with_worker_session_factory(_make_run_scan(mac_address, ip_address)))


async def queue_port_scan(
    mac_address: str,
    ip_address: str,
    session_factory: Optional[async_sessionmaker[AsyncSession]] = None
) -> bool:
    """Queue a port scan task for a device
    
    Args:
        mac_address: Device MAC address
        ip_address: Device IP address
        session_factory: Optional session factory (for worker context)
    
    Returns:
        bool: True if scan was queued, False if already in progress
    """
    factory = session_factory or AsyncSessionLocal
    async with factory() as session:
        # Check if there's already a pending or in-progress scan
        result = await session.execute(
            select(DevicePortScanDB).where(
                DevicePortScanDB.mac_address == mac_address,
                DevicePortScanDB.scan_status.in_(['pending', 'in_progress'])
            )
        )
        existing_scan = result.scalar_one_or_none()
        
        if existing_scan:
            logger.debug(f"Port scan already queued/in-progress for {mac_address}")
            return False
        
        # Check if device is online
        device_result = await session.execute(
            select(NetworkDeviceDB).where(
                NetworkDeviceDB.mac_address == mac_address
            )
        )
        device = device_result.scalar_one_or_none()
        
        if device and not device.is_online:
            logger.debug(f"Device {mac_address} is offline, skipping port scan")
            return False
        
        # Create pending scan record
        scan_record = DevicePortScanDB(
            mac_address=mac_address,
            ip_address=ip_address,
            scan_status='pending',
            scan_started_at=datetime.now(timezone.utc)
        )
        session.add(scan_record)
        await session.commit()
        
        # Queue the Celery task
        scan_device_ports_task.delay(mac_address, ip_address)
        logger.info(f"Queued port scan for device {mac_address} at {ip_address}")
        return True


async def queue_new_device_scan(
    mac_address: str,
    ip_address: str,
    session_factory: Optional[async_sessionmaker[AsyncSession]] = None
) -> bool:
    """Queue a port scan for a newly discovered device (if never scanned before)

    Args:
        mac_address: Device MAC address
        ip_address: Device IP address
        session_factory: Optional session factory (for worker context)

    Returns:
        bool: True if scan was queued, False if already scanned or in progress
    """
    factory = session_factory or AsyncSessionLocal
    async with factory() as session:
        # Check if device has EVER been scanned (any status)
        result = await session.execute(
            select(DevicePortScanDB).where(
                DevicePortScanDB.mac_address == mac_address
            )
        )
        any_scan = result.scalars().first()

        if any_scan:
            logger.debug(
                f"Device {mac_address} already has scan history, skipping new device scan"
            )
            return False

        # Check if there's already a pending or in-progress scan
        pending_result = await session.execute(
            select(DevicePortScanDB).where(
                DevicePortScanDB.mac_address == mac_address,
                DevicePortScanDB.scan_status.in_(['pending', 'in_progress'])
            )
        )
        pending_scan = pending_result.scalar_one_or_none()

        if pending_scan:
            logger.debug(f"Port scan already queued/in-progress for {mac_address}")
            return False

        # Create pending scan record
        scan_record = DevicePortScanDB(
            mac_address=mac_address,
            ip_address=ip_address,
            scan_status='pending',
            scan_started_at=datetime.now(timezone.utc)
        )
        session.add(scan_record)
        await session.commit()

        # Queue to the NEW DEVICE scan task (sequential queue)
        scan_new_device_ports_task.delay(mac_address, ip_address)
        logger.info(f"Queued NEW device port scan for {mac_address} at {ip_address}")
        return True

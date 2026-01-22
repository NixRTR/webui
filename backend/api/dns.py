"""
DNS management API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import subprocess
import os
import shutil
import logging

from ..database import get_db, DnsZoneDB, DnsRecordDB, DnsConfigHistoryDB
from ..models import (
    DnsZone, DnsZoneCreate, DnsZoneUpdate,
    DnsRecord, DnsRecordCreate, DnsRecordUpdate
)
from ..api.auth import get_current_user
from ..collectors.services import get_service_status
from ..utils.dnsmasq_dns import generate_dnsmasq_dns_config
from ..utils.config_writer import write_dns_config
from ..utils.dnsmasq_parser import sync_dnsmasq_config_to_database
from ..utils.dns import migrate_dns_config_to_database
import json
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dns", tags=["dns"])

# Map network names to systemd service names
NETWORK_SERVICE_MAP = {
    'homelab': 'dnsmasq-homelab',
    'lan': 'dnsmasq-lan',
}


async def _save_dns_config_history(
    db: AsyncSession,
    network: str,
    change_type: str,
    changed_by: str,
    change_details: dict
) -> None:
    """Save DNS configuration change to history
    
    Args:
        db: Database session
        network: Network name
        change_type: Type of change ("create", "update", "delete")
        changed_by: Username who made the change
        change_details: Additional details about the change
    """
    # Get current DNS configuration snapshot
    result = await db.execute(
        select(DnsZoneDB)
        .where(DnsZoneDB.network == network)
        .order_by(DnsZoneDB.name)
    )
    zones = result.scalars().all()
    
    # Build config snapshot
    config_snapshot = {
        'zones': []
    }
    
    for zone in zones:
        zone_data = {
            'id': zone.id,
            'name': zone.name,
            'authoritative': zone.authoritative,
            'forward_to': zone.forward_to,
            'delegate_to': zone.delegate_to,
            'enabled': zone.enabled,
            'records': []
        }
        
        # Get records for this zone
        result = await db.execute(
            select(DnsRecordDB)
            .where(DnsRecordDB.zone_id == zone.id)
            .order_by(DnsRecordDB.name)
        )
        records = result.scalars().all()
        
        for record in records:
            zone_data['records'].append({
                'id': record.id,
                'name': record.name,
                'type': record.type,
                'value': record.value,
                'comment': record.comment,
                'enabled': record.enabled,
            })
        
        config_snapshot['zones'].append(zone_data)
    
    # Save to history
    history = DnsConfigHistoryDB(
        network=network,
        change_type=change_type,
        changed_by=changed_by,
        config_snapshot=config_snapshot,
        change_details=change_details
    )
    db.add(history)
    await db.commit()


async def _write_dns_config_and_reload(
    db: AsyncSession,
    network: str,
    changed_by: str,
    change_type: str,
    change_details: dict
) -> None:
    """Generate DNS config, write it, and reload dnsmasq service
    
    Args:
        db: Database session
        network: Network name
        changed_by: Username who made the change
        change_type: Type of change
        change_details: Additional details about the change
    """
    try:
        # Save history
        await _save_dns_config_history(db, network, change_type, changed_by, change_details)
        
        # Generate config
        config_content = await generate_dnsmasq_dns_config(db, network)
        
        # Write config via helper service
        write_dns_config(network, config_content)
        
        # Reload dnsmasq service
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        _control_service_via_systemctl(service_name, "reload")
        
        logger.info(f"DNS config written and service reloaded for network {network}")
    except Exception as e:
        logger.error(f"Failed to write DNS config for network {network}: {e}", exc_info=True)
        # Don't raise - allow the API call to succeed even if config write fails
        # The database change is already committed


def _find_sudo() -> str:
    """Find sudo binary path (NixOS way)
    
    In NixOS, we need to use the wrapped sudo from /run/wrappers/bin/sudo
    which has the setuid bit set. The store path sudo doesn't have setuid.
    """
    # First try shutil.which (uses PATH, should find the wrapper)
    sudo_path = shutil.which('sudo')
    if sudo_path:
        return sudo_path
    
    # Try NixOS wrapper path (has setuid bit)
    wrapper_path = '/run/wrappers/bin/sudo'
    if os.path.exists(wrapper_path) and os.access(wrapper_path, os.X_OK):
        return wrapper_path
    
    # Fallback to other common paths
    candidates = [
        '/run/current-system/sw/bin/sudo',
        '/usr/bin/sudo',
        '/bin/sudo',
    ]
    
    for path in candidates:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    
    logger.error("sudo binary not found in any location")
    raise RuntimeError("sudo binary not found. Please ensure sudo is installed.")


def _find_systemctl() -> str:
    """Find systemctl binary path (NixOS way)"""
    # Check environment variable first (set by NixOS service)
    env_path = os.environ.get("SYSTEMCTL_BIN")
    if env_path and os.path.exists(env_path):
        return env_path
    
    # Try common paths
    candidates = [
        '/run/current-system/sw/bin/systemctl',
        '/usr/bin/systemctl',
        '/bin/systemctl',
    ]
    
    for path in candidates:
        if os.path.exists(path) and os.access(path, os.X_OK):
            return path
    
    logger.error("systemctl binary not found in any location")
    raise RuntimeError("systemctl binary not found. Please ensure systemd is installed.")


def _control_service_via_systemctl(service_name: str, action: str) -> None:
    """Control a systemd service via socket-activated helper service (runs as root)
    
    Uses a socket-activated service that runs as root and accepts commands via
    a Unix socket. This follows NixOS best practices by avoiding direct sudo
    usage in systemd services.
    
    Args:
        service_name: Name of the service (e.g., "dnsmasq-homelab.service")
        action: Action to perform ("start", "stop", "restart", "reload")
        
    Raises:
        subprocess.CalledProcessError: If the command fails
    """
    # Validate action
    valid_actions = ['start', 'stop', 'restart', 'reload']
    if action.lower() not in valid_actions:
        logger.error(f"Invalid action: {action}")
        raise ValueError(f"Invalid action: {action}. Must be one of: {valid_actions}")
    
    socket_path = "/run/router-webui/service-control.sock"
    
    # Send command to socket (format: "ACTION SERVICE\n")
    try:
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(socket_path)
        command = f"{action.lower()} {service_name}\n"
        sock.sendall(command.encode('utf-8'))
        sock.shutdown(socket.SHUT_WR)
        
        # Read response
        response = b""
        while True:
            data = sock.recv(4096)
            if not data:
                break
            response += data
        
        sock.close()
        
        # Check if there was an error in the response
        response_str = response.decode('utf-8', errors='ignore')
        if "Invalid" in response_str or "Failed" in response_str or "error" in response_str.lower():
            logger.error(f"Service control returned error: {response_str}")
            raise subprocess.CalledProcessError(1, f"socket command", stderr=response_str)
        
    except (socket.error, OSError) as e:
        logger.error(f"Failed to communicate with service control socket: {e}")
        raise subprocess.CalledProcessError(1, f"socket command", stderr=str(e))


@router.get("/zones", response_model=List[DnsZone])
async def get_zones(
    network: Optional[str] = None,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[DnsZone]:
    """Get list of DNS zones
    
    Args:
        network: Optional filter by network ("homelab" or "lan")
        
    Returns:
        List of DNS zones
    """
    query = select(DnsZoneDB)
    if network:
        if network not in ['homelab', 'lan']:
            raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
        query = query.where(DnsZoneDB.network == network)
    
    query = query.order_by(DnsZoneDB.network, DnsZoneDB.name)
    result = await db.execute(query)
    zones = result.scalars().all()
    
    return [DnsZone.model_validate(zone) for zone in zones]


@router.post("/zones", response_model=DnsZone)
async def create_zone(
    zone: DnsZoneCreate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsZone:
    """Create a new DNS zone
    
    Args:
        zone: Zone creation data
        
    Returns:
        Created zone
    """
    # Check if zone with same name and network already exists
    result = await db.execute(
        select(DnsZoneDB).where(
            DnsZoneDB.name == zone.name,
            DnsZoneDB.network == zone.network
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Zone {zone.name} already exists for network {zone.network}"
        )
    
    db_zone = DnsZoneDB(
        name=zone.name,
        network=zone.network,
        authoritative=zone.authoritative,
        forward_to=zone.forward_to,
        delegate_to=zone.delegate_to,
        enabled=zone.enabled,
        original_config_path=zone.original_config_path
    )
    db.add(db_zone)
    await db.commit()
    await db.refresh(db_zone)
    
    # Write config and reload service
    await _write_dns_config_and_reload(
        db, zone.network, username, "create",
        {"zone_id": db_zone.id, "zone_name": zone.name}
    )
    
    return DnsZone.model_validate(db_zone)


@router.get("/zones/{zone_id}", response_model=DnsZone)
async def get_zone(
    zone_id: int,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsZone:
    """Get a specific DNS zone by ID
    
    Args:
        zone_id: Zone ID
        
    Returns:
        Zone details
    """
    result = await db.execute(
        select(DnsZoneDB).where(DnsZoneDB.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    
    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone {zone_id} not found"
        )
    
    return DnsZone.model_validate(zone)


@router.put("/zones/{zone_id}", response_model=DnsZone)
async def update_zone(
    zone_id: int,
    zone_update: DnsZoneUpdate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsZone:
    """Update a DNS zone
    
    Args:
        zone_id: Zone ID
        zone_update: Zone update data
        
    Returns:
        Updated zone
    """
    result = await db.execute(
        select(DnsZoneDB).where(DnsZoneDB.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    
    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone {zone_id} not found"
        )
    
    # Store original network for config update
    original_network = zone.network
    
    # Check for name/network conflict if updating name or network
    if zone_update.name is not None or zone_update.network is not None:
        new_name = zone_update.name if zone_update.name is not None else zone.name
        new_network = zone_update.network if zone_update.network is not None else zone.network
        
        if new_name != zone.name or new_network != zone.network:
            result = await db.execute(
                select(DnsZoneDB).where(
                    DnsZoneDB.name == new_name,
                    DnsZoneDB.network == new_network,
                    DnsZoneDB.id != zone_id
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Zone {new_name} already exists for network {new_network}"
                )
    
    # Update fields
    if zone_update.name is not None:
        zone.name = zone_update.name
    if zone_update.network is not None:
        zone.network = zone_update.network
    if zone_update.authoritative is not None:
        zone.authoritative = zone_update.authoritative
    if zone_update.forward_to is not None:
        zone.forward_to = zone_update.forward_to
    if zone_update.delegate_to is not None:
        zone.delegate_to = zone_update.delegate_to
    if zone_update.enabled is not None:
        zone.enabled = zone_update.enabled
    
    await db.commit()
    await db.refresh(zone)
    
    # Write config and reload service (for both old and new network if changed)
    networks_to_update = {original_network}
    if zone.network != original_network:
        networks_to_update.add(zone.network)
    
    for network in networks_to_update:
        await _write_dns_config_and_reload(
            db, network, username, "update",
            {"zone_id": zone_id, "zone_name": zone.name}
        )
    
    return DnsZone.model_validate(zone)


@router.delete("/zones/{zone_id}")
async def delete_zone(
    zone_id: int,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a DNS zone (cascades to records)
    
    Args:
        zone_id: Zone ID
        
    Returns:
        Success message
    """
    result = await db.execute(
        select(DnsZoneDB).where(DnsZoneDB.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    
    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone {zone_id} not found"
        )
    
    network = zone.network
    zone_name = zone.name
    
    await db.delete(zone)
    await db.commit()
    
    # Write config and reload service
    await _write_dns_config_and_reload(
        db, network, username, "delete",
        {"zone_id": zone_id, "zone_name": zone_name}
    )
    
    return {"message": f"Zone {zone_id} deleted successfully"}


@router.get("/zones/{zone_id}/records", response_model=List[DnsRecord])
async def get_zone_records(
    zone_id: int,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[DnsRecord]:
    """Get all records for a zone
    
    Args:
        zone_id: Zone ID
        
    Returns:
        List of DNS records
    """
    # Verify zone exists
    result = await db.execute(
        select(DnsZoneDB).where(DnsZoneDB.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone {zone_id} not found"
        )
    
    result = await db.execute(
        select(DnsRecordDB)
        .where(DnsRecordDB.zone_id == zone_id)
        .order_by(DnsRecordDB.type, DnsRecordDB.name)
    )
    records = result.scalars().all()
    
    return [DnsRecord.model_validate(record) for record in records]


@router.post("/zones/{zone_id}/records", response_model=DnsRecord)
async def create_record(
    zone_id: int,
    record: DnsRecordCreate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsRecord:
    """Create a new DNS record in a zone
    
    Args:
        zone_id: Zone ID
        record: Record creation data (zone_id in record is ignored, uses path param)
        
    Returns:
        Created record
    """
    # Verify zone exists
    result = await db.execute(
        select(DnsZoneDB).where(DnsZoneDB.id == zone_id)
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone {zone_id} not found"
        )
    
    # Validate record type
    if record.type not in ['A', 'CNAME']:
        raise HTTPException(
            status_code=400,
            detail="Record type must be 'A' or 'CNAME'"
        )
    
    # Validate A record value (must be IP address)
    if record.type == 'A':
        import ipaddress
        try:
            ipaddress.IPv4Address(record.value)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="A record value must be a valid IPv4 address"
            )
    
    db_record = DnsRecordDB(
        zone_id=zone_id,
        name=record.name,
        type=record.type,
        value=record.value,
        comment=record.comment,
        enabled=record.enabled,
        original_config_path=record.original_config_path
    )
    db.add(db_record)
    await db.commit()
    await db.refresh(db_record)
    
    # Write config and reload service
    await _write_dns_config_and_reload(
        db, zone.network, username, "create",
        {"record_id": db_record.id, "record_name": record.name, "zone_id": zone_id}
    )
    
    return DnsRecord.model_validate(db_record)


@router.get("/records/{record_id}", response_model=DnsRecord)
async def get_record(
    record_id: int,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsRecord:
    """Get a specific DNS record by ID
    
    Args:
        record_id: Record ID
        
    Returns:
        Record details
    """
    result = await db.execute(
        select(DnsRecordDB).where(DnsRecordDB.id == record_id)
    )
    record = result.scalar_one_or_none()
    
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Record {record_id} not found"
        )
    
    return DnsRecord.model_validate(record)


@router.put("/records/{record_id}", response_model=DnsRecord)
async def update_record(
    record_id: int,
    record_update: DnsRecordUpdate,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsRecord:
    """Update a DNS record
    
    Args:
        record_id: Record ID
        record_update: Record update data
        
    Returns:
        Updated record
    """
    result = await db.execute(
        select(DnsRecordDB).where(DnsRecordDB.id == record_id)
    )
    record = result.scalar_one_or_none()
    
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Record {record_id} not found"
        )
    
    # If moving to a different zone, verify it exists
    if record_update.zone_id is not None and record_update.zone_id != record.zone_id:
        result = await db.execute(
            select(DnsZoneDB).where(DnsZoneDB.id == record_update.zone_id)
        )
        new_zone = result.scalar_one_or_none()
        if not new_zone:
            raise HTTPException(
                status_code=404,
                detail=f"Zone {record_update.zone_id} not found"
            )
        record.zone_id = record_update.zone_id
    
    # Validate record type if changing
    if record_update.type is not None:
        if record_update.type not in ['A', 'CNAME']:
            raise HTTPException(
                status_code=400,
                detail="Record type must be 'A' or 'CNAME'"
            )
        record.type = record_update.type
    
    # Validate A record value if changing
    if record_update.value is not None:
        record_type = record_update.type if record_update.type is not None else record.type
        if record_type == 'A':
            import ipaddress
            try:
                ipaddress.IPv4Address(record_update.value)
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="A record value must be a valid IPv4 address"
                )
        record.value = record_update.value
    
    # Update other fields
    if record_update.name is not None:
        record.name = record_update.name
    if record_update.comment is not None:
        record.comment = record_update.comment
    if record_update.enabled is not None:
        record.enabled = record_update.enabled
    
    # Get zone to determine network
    result = await db.execute(
        select(DnsZoneDB).where(DnsZoneDB.id == record.zone_id)
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    
    await db.commit()
    await db.refresh(record)
    
    # Write config and reload service
    await _write_dns_config_and_reload(
        db, zone.network, username, "update",
        {"record_id": record_id, "record_name": record.name, "zone_id": record.zone_id}
    )
    
    return DnsRecord.model_validate(record)


@router.delete("/records/{record_id}")
async def delete_record(
    record_id: int,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a DNS record
    
    Args:
        record_id: Record ID
        
    Returns:
        Success message
    """
    result = await db.execute(
        select(DnsRecordDB).where(DnsRecordDB.id == record_id)
    )
    record = result.scalar_one_or_none()
    
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Record {record_id} not found"
        )
    
    # Get zone to determine network before deleting
    result = await db.execute(
        select(DnsZoneDB).where(DnsZoneDB.id == record.zone_id)
    )
    zone = result.scalar_one_or_none()
    if not zone:
        raise HTTPException(status_code=404, detail="Zone not found")
    
    network = zone.network
    record_name = record.name
    
    await db.delete(record)
    await db.commit()
    
    # Write config and reload service
    await _write_dns_config_and_reload(
        db, network, username, "delete",
        {"record_id": record_id, "record_name": record_name, "zone_id": record.zone_id}
    )
    
    return {"message": f"Record {record_id} deleted successfully"}


@router.get("/service-status/{network}")
async def get_dns_service_status(
    network: str,
    _: str = Depends(get_current_user)
):
    """Get DNS service status for a network
    
    Uses systemctl to retrieve status (same approach as other services).
    Reading status doesn't require sudo, only control operations do.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        Service status information
    """
    if network not in NETWORK_SERVICE_MAP:
        logger.warning(f"Invalid network requested: {network}")
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    service_name = NETWORK_SERVICE_MAP[network]
    
    # Use the same get_service_status function that other services use
    # This uses systemctl which works for reading status without sudo
    status = get_service_status(service_name)
    
    if status is None:
        return {
            "network": network,
            "service_name": service_name,
            "is_active": False,
            "is_enabled": False,
            "exists": False
        }
    
    return {
        "network": network,
        "service_name": service_name,
        "is_active": status.is_active,
        "is_enabled": status.is_enabled,
        "exists": True,
        "pid": status.pid,
        "memory_mb": status.memory_mb,
        "cpu_percent": status.cpu_percent
    }


@router.post("/service/{network}/{action}")
async def control_dns_service(
    network: str,
    action: str,
    _: str = Depends(get_current_user)
):
    """Control DNS service for a network
    
    Args:
        network: Network name ("homelab" or "lan")
        action: Action to perform ("start", "stop", "restart", "reload")
        
    Returns:
        Success message
    """
    if network not in NETWORK_SERVICE_MAP:
        logger.warning(f"Invalid network requested: {network}")
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    if action not in ['start', 'stop', 'restart', 'reload']:
        logger.warning(f"Invalid action requested: {action}")
        raise HTTPException(status_code=400, detail="Action must be 'start', 'stop', 'restart', or 'reload'")
    
    service_name = NETWORK_SERVICE_MAP[network]
    full_service_name = f"{service_name}.service"
    
    try:
        # Use sudo systemctl to control the service
        _control_service_via_systemctl(full_service_name, action)
        logger.info(f"Successfully {action}ed service {service_name} for network {network}")
        
        return {
            "message": f"Service {service_name} {action}ed successfully",
            "network": network,
            "action": action,
            "service_name": service_name
        }
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr or e.stdout or str(e)
        logger.error(f"Failed to {action} service {service_name}: returncode={e.returncode}, stderr={e.stderr[:500] if e.stderr else None}, stdout={e.stdout[:500] if e.stdout else None}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to {action} service {service_name}: {error_msg}"
        )
    except (subprocess.TimeoutExpired, ValueError, RuntimeError) as e:
        logger.error(f"Error while trying to {action} service {service_name}: {type(e).__name__}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error while trying to {action} service {service_name}: {str(e)}"
        )


@router.post("/revert/{network}/{history_id}")
async def revert_dns_config(
    network: str,
    history_id: int,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Revert DNS configuration to a previous state
    
    Args:
        network: Network name ("homelab" or "lan")
        history_id: History record ID to revert to
        
    Returns:
        Success message
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Get history record
    result = await db.execute(
        select(DnsConfigHistoryDB)
        .where(
            DnsConfigHistoryDB.id == history_id,
            DnsConfigHistoryDB.network == network
        )
    )
    history = result.scalar_one_or_none()
    
    if not history:
        raise HTTPException(
            status_code=404,
            detail=f"History record {history_id} not found for network {network}"
        )
    
    if history.status == 'reverted':
        raise HTTPException(
            status_code=400,
            detail=f"History record {history_id} has already been reverted"
        )
    
    # Restore configuration from snapshot
    config_snapshot = history.config_snapshot
    
    # Delete all existing zones and records for this network
    result = await db.execute(
        select(DnsZoneDB).where(DnsZoneDB.network == network)
    )
    zones = result.scalars().all()
    for zone in zones:
        await db.delete(zone)
    
    # Restore zones and records from snapshot
    for zone_data in config_snapshot.get('zones', []):
        db_zone = DnsZoneDB(
            id=zone_data['id'],
            name=zone_data['name'],
            network=network,
            authoritative=zone_data['authoritative'],
            forward_to=zone_data.get('forward_to'),
            delegate_to=zone_data.get('delegate_to'),
            enabled=zone_data['enabled']
        )
        db.add(db_zone)
        await db.flush()  # Flush to get zone ID
        
        # Restore records
        for record_data in zone_data.get('records', []):
            db_record = DnsRecordDB(
                id=record_data['id'],
                zone_id=db_zone.id,
                name=record_data['name'],
                type=record_data['type'],
                value=record_data['value'],
                comment=record_data.get('comment'),
                enabled=record_data['enabled']
            )
            db.add(db_record)
    
    # Mark history record as reverted
    history.status = 'reverted'
    history.reverted_by = username
    history.reverted_at = datetime.utcnow()
    
    await db.commit()
    
    # Write config and reload service
    await _write_dns_config_and_reload(
        db, network, username, "revert",
        {"history_id": history_id, "reverted_from": history.change_type}
    )
    
    return {
        "message": f"DNS configuration reverted to history record {history_id}",
        "network": network,
        "history_id": history_id
    }


@router.post("/sync-config/{network}")
async def sync_dns_config(
    network: str,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Sync DNS configuration from database to dnsmasq config files
    
    This endpoint writes the current database state to the dnsmasq config files.
    Useful for syncing existing records that were added before the config writer was implemented.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        Success message
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    try:
        # Write config and reload service (without creating a history entry for sync)
        config_content = await generate_dnsmasq_dns_config(db, network)
        write_dns_config(network, config_content)
        
        # Reload dnsmasq service
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        _control_service_via_systemctl(service_name, "reload")
        
        logger.info(f"DNS config synced for network {network}")
        
        return {
            "message": f"DNS configuration synced for network {network}",
            "network": network
        }
    except Exception as e:
        logger.error(f"Failed to sync DNS config for network {network}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync DNS config: {str(e)}"
        )


@router.post("/import-from-config/{network}")
async def import_dns_from_config(
    network: str,
    source: str = "dnsmasq",  # "dnsmasq" or "router-config"
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Import DNS configuration from config files to database
    
    This endpoint reads configuration from either dnsmasq config files or router-config.nix
    and syncs them to the database. Useful for importing existing configurations.
    
    Args:
        network: Network name ("homelab" or "lan")
        source: Source to import from - "dnsmasq" (reads dnsmasq config files) or 
                "router-config" (reads router-config.nix). Default: "dnsmasq"
        
    Returns:
        Success message with counts of imported records
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    if source not in ['dnsmasq', 'router-config']:
        raise HTTPException(status_code=400, detail="Source must be 'dnsmasq' or 'router-config'")
    
    try:
        if source == "dnsmasq":
            # Import from dnsmasq config files
            zones_updated, records_updated = await sync_dnsmasq_config_to_database(db, network)
            
            logger.info(f"Imported {zones_updated} zones and {records_updated} records from dnsmasq configs for network {network}")
            
            return {
                "message": f"DNS configuration imported from dnsmasq config files",
                "network": network,
                "source": source,
                "zones_updated": zones_updated,
                "records_updated": records_updated
            }
        else:
            # Import from router-config.nix
            await migrate_dns_config_to_database(db)
            
            logger.info(f"Imported DNS configuration from router-config.nix for network {network}")
            
            return {
                "message": f"DNS configuration imported from router-config.nix",
                "network": network,
                "source": source
            }
    except Exception as e:
        logger.error(f"Failed to import DNS config for network {network}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import DNS config: {str(e)}"
        )


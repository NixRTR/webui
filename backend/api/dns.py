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

from ..database import get_db, DnsConfigHistoryDB, DnsZoneDB
from ..models import (
    DnsZone, DnsZoneCreate, DnsZoneUpdate,
    DnsRecord, DnsRecordCreate, DnsRecordUpdate,
    DynamicDnsEntry,
    DnsNetworkSettings,
)
from ..api.auth import get_current_user
from ..collectors.services import get_service_status
from ..collectors.dhcp import parse_dnsmasq_leases
from ..utils.dnsmasq_dns import generate_dnsmasq_dns_config
from ..utils.config_writer import write_dns_config
from ..utils.config_reader import (
    get_dns_zones_from_config,
    get_dns_records_from_config,
    get_dhcp_networks_from_config,
)
from ..utils.config_manager import update_dns_record_in_config
from ..utils.dnsmasq_parser import parse_dnsmasq_config_file
from ..utils.dns import parse_dns_nix_file
from ..utils.config_writer import write_dns_nix_config
from ..utils.nix_writer import format_nix_dict
from ..utils.redis_client import get_json, set_json, delete as redis_delete
import json
from datetime import datetime
import os

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
    
    Reads current config from files and saves snapshot to history database.
    
    Args:
        db: Database session
        network: Network name
        change_type: Type of change ("create", "update", "delete")
        changed_by: Username who made the change
        change_details: Additional details about the change
    """
    # Get current DNS configuration snapshot from config files
    zones = get_dns_zones_from_config(network)
    all_records = get_dns_records_from_config(network)
    
    # Build config snapshot
    config_snapshot = {
        'zones': []
    }
    
    # Group records by zone
    records_by_zone = {}
    for record in all_records:
        zone_name = record['zone_name']
        if zone_name not in records_by_zone:
            records_by_zone[zone_name] = []
        records_by_zone[zone_name].append(record)
    
    # Build zone snapshots
    for zone in zones:
        zone_name = zone['name']
        zone_data = {
            'name': zone_name,
            'authoritative': zone.get('authoritative', True),
            'enabled': zone.get('enabled', True),
            'records': []
        }
        
        # Get records for this zone
        zone_records = records_by_zone.get(zone_name, [])
        for record in zone_records:
            zone_data['records'].append({
                'name': record['name'],
                'type': record['type'],
                'value': record['value'],
                'comment': record.get('comment', ''),
                'enabled': record.get('enabled', True),
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
    """Generate DNS config from files, write it, and reload dnsmasq service
    
    Args:
        db: Database session (for history tracking only)
        network: Network name
        changed_by: Username who made the change
        change_type: Type of change
        change_details: Additional details about the change
    """
    try:
        # Save history (before writing, to capture current state)
        await _save_dns_config_history(db, network, change_type, changed_by, change_details)
        
        # Generate config from files (router-config.nix + webui-dns.conf)
        config_content = await generate_dnsmasq_dns_config(network, db)
        
        # Write config via helper service
        write_dns_config(network, config_content)
        
        # Restart dnsmasq service (dnsmasq doesn't support reload)
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        try:
            _control_service_via_systemctl(service_name, "restart")
            logger.info(f"DNS config written and service restarted for network {network}")
        except Exception as restart_error:
            logger.error(f"Failed to restart {service_name}: {restart_error}")
            # Don't raise - allow the API call to succeed even if service control fails
    except Exception as e:
        logger.error(f"Failed to write DNS config for network {network}: {e}", exc_info=True)
        # Don't raise - allow the API call to succeed even if config write fails


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


@router.get("/networks/{network}/dynamic-entries", response_model=List[DynamicDnsEntry])
async def get_dynamic_dns_entries(
    network: str,
    _: str = Depends(get_current_user),
) -> List[DynamicDnsEntry]:
    """Get dynamic DNS entries for a network (from DHCP leases; read-only).
    
    When dynamic_domain is set for the network, each DHCP lease becomes a
    host-record=hostname.domain,ip. This endpoint returns that list.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        List of dynamic DNS entries (hostname, hostname_fqdn, ip_address, mac_address, network)
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    networks_cfg = get_dhcp_networks_from_config()
    net_cfg = next((n for n in networks_cfg if n['network'] == network), None)
    dynamic_domain = (net_cfg.get('dynamic_domain') or '').strip() if net_cfg else ''
    
    if not dynamic_domain:
        return []
    
    leases = parse_dnsmasq_leases()
    entries = []
    for lease in leases:
        if lease.network != network:
            continue
        # Match Nix logic: short hostname is lease hostname, or "dhcp-{last_octet}" when empty
        if lease.hostname and not lease.hostname.startswith('client-'):
            short_hostname = lease.hostname
        else:
            short_hostname = f"dhcp-{lease.ip_address.split('.')[-1]}"
        hostname_fqdn = f"{short_hostname}.{dynamic_domain}"
        entries.append(DynamicDnsEntry(
            hostname=short_hostname,
            hostname_fqdn=hostname_fqdn,
            ip_address=lease.ip_address,
            mac_address=lease.mac_address,
            network=lease.network,
        ))
    return entries


@router.get("/zones", response_model=List[DnsZone])
async def get_zones(
    network: Optional[str] = None,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[DnsZone]:
    """Get list of DNS zones from config files (source of truth)
    
    Args:
        network: Optional filter by network ("homelab" or "lan")
        
    Returns:
        List of DNS zones
    """
    cache_key = f"api:dns:zones:{network or 'all'}"
    cached = await get_json(cache_key)
    if cached:
        return [DnsZone.model_validate(z) for z in cached]

    all_zones = []
    
    networks = ['homelab', 'lan'] if not network else [network]
    if network and network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Get hosting modes from database
    from sqlalchemy import select
    result = await db.execute(select(DnsZoneDB))
    db_zones = result.scalars().all()
    hosting_modes = {(z.network, z.name): z.hosting_mode for z in db_zones}
    
    for net in networks:
        zones = get_dns_zones_from_config(net)
        for zone_dict in zones:
            # Convert to DnsZone model (assigning temporary IDs for API compatibility)
            zone_dict['id'] = hash(f"{net}:{zone_dict['name']}") % (2**31)  # Temporary ID
            # Merge hosting_mode from database
            zone_dict['hosting_mode'] = hosting_modes.get((net, zone_dict['name']), 'fully_hosted')
            all_zones.append(DnsZone.model_validate(zone_dict))
    
    out = sorted(all_zones, key=lambda z: (z.network, z.name))
    await set_json(cache_key, [z.model_dump(mode="json") for z in out], ttl=30)
    return out


@router.post("/zones", response_model=DnsZone)
async def create_zone(
    zone: DnsZoneCreate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsZone:
    """Create a new DNS zone (zones are auto-discovered from records)
    
    Note: Zones are automatically discovered from DNS records. This endpoint
    validates that the zone doesn't already exist, but zones are created
    implicitly when records are added.
    
    Args:
        zone: Zone creation data
        
    Returns:
        Created zone (read from config)
    """
    if zone.network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Check if zone already exists in config
    zones = get_dns_zones_from_config(zone.network)
    existing = next((z for z in zones if z['name'] == zone.name), None)
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Zone {zone.name} already exists for network {zone.network}"
        )
    
    # Zones are auto-discovered from records, so we just validate
    # The zone will appear when records are added to it
    # For now, return the zone as it would appear (with default settings)
    zone_dict = {
        'name': zone.name,
        'network': zone.network,
        'authoritative': zone.authoritative if zone.authoritative is not None else True,
        'enabled': zone.enabled if zone.enabled is not None else True,
        'id': hash(f"{zone.network}:{zone.name}") % (2**31)
    }
    
    return DnsZone.model_validate(zone_dict)


@router.get("/zones/{zone_name}", response_model=DnsZone)
async def get_zone(
    zone_name: str,
    network: str,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsZone:
    """Get a specific DNS zone by name from config files
    
    Args:
        zone_name: Zone name (e.g., "jeandr.net")
        network: Network name ("homelab" or "lan")
        
    Returns:
        Zone details
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    cache_key = f"api:dns:zone:{network}:{zone_name}"
    cached = await get_json(cache_key)
    if cached:
        return DnsZone.model_validate(cached)
    
    zones = get_dns_zones_from_config(network)
    zone = next((z for z in zones if z['name'] == zone_name), None)
    
    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone {zone_name} not found for network {network}"
        )
    
    # Convert to DnsZone model (assigning temporary ID for API compatibility)
    zone['id'] = hash(f"{network}:{zone_name}") % (2**31)
    out = DnsZone.model_validate(zone)
    await set_json(cache_key, out.model_dump(mode="json"), ttl=30)
    return out


@router.put("/zones/{zone_name}", response_model=DnsZone)
async def update_zone(
    zone_name: str,
    network: str,
    zone_update: DnsZoneUpdate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsZone:
    """Update a DNS zone (zone metadata only - authoritative flag affects config generation)
    
    Note: Zone-level settings like authoritative, forward_to, delegate_to are metadata
    that affect how records are generated. The actual zone is auto-discovered from records.
    
    Args:
        zone_name: Zone name (e.g., "jeandr.net")
        network: Network name ("homelab" or "lan")
        zone_update: Zone update data
        
    Returns:
        Updated zone
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Verify zone exists in config
    zones = get_dns_zones_from_config(network)
    zone = next((z for z in zones if z['name'] == zone_name), None)
    
    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone {zone_name} not found for network {network}"
        )
    
    # For now, zones are auto-discovered from records
    # Zone metadata (authoritative, forward_to, delegate_to) would need to be stored
    # in a separate metadata file or in webui-dns.conf comments
    # For simplicity, we'll just regenerate config which will use authoritative=True by default
    
    # If zone name or network is being changed, that's not supported (zones are auto-discovered)
    if zone_update.name is not None and zone_update.name != zone_name:
        raise HTTPException(
            status_code=400,
            detail="Zone name cannot be changed - zones are auto-discovered from records"
        )
    if zone_update.network is not None and zone_update.network != network:
        raise HTTPException(
            status_code=400,
            detail="Zone network cannot be changed - zones are auto-discovered from records"
        )
    
    # Update hosting_mode in database if provided
    from sqlalchemy import select
    
    if zone_update.hosting_mode is not None:
        result = await db.execute(
            select(DnsZoneDB).where(
                DnsZoneDB.network == network,
                DnsZoneDB.name == zone_name
            )
        )
        db_zone = result.scalar_one_or_none()
        
        if db_zone:
            # Update existing zone
            db_zone.hosting_mode = zone_update.hosting_mode
        else:
            # Create new zone entry
            db_zone = DnsZoneDB(
                network=network,
                name=zone_name,
                enabled=True,
                hosting_mode=zone_update.hosting_mode
            )
            db.add(db_zone)
        
        # Commit database changes BEFORE regenerating config
        # (config generation queries the database for hosting modes)
        await db.commit()
        
        # Invalidate zones cache
        await redis_delete(f"api:dns:zones:{network}")
        await redis_delete("api:dns:zones:all")
        
        # Regenerate dnsmasq config with new hosting_mode and restart service
        await _write_dns_config_and_reload(
            db, network, username, "update",
            {"zone_name": zone_name, "hosting_mode": zone_update.hosting_mode}
        )
    
    # Return updated zone (read back from config)
    zones = get_dns_zones_from_config(network)
    updated_zone = next((z for z in zones if z['name'] == zone_name), None)
    if not updated_zone:
        raise HTTPException(status_code=404, detail=f"Zone {zone_name} not found after update")
    
    updated_zone['id'] = hash(f"{network}:{zone_name}") % (2**31)
    
    # Get hosting_mode from database
    result = await db.execute(
        select(DnsZoneDB).where(
            DnsZoneDB.network == network,
            DnsZoneDB.name == zone_name
        )
    )
    db_zone = result.scalar_one_or_none()
    updated_zone['hosting_mode'] = db_zone.hosting_mode if db_zone else 'fully_hosted'
    
    return DnsZone.model_validate(updated_zone)


@router.delete("/zones/{zone_name}")
async def delete_zone(
    zone_name: str,
    network: str,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a DNS zone by deleting all records in the zone
    
    Args:
        zone_name: Zone name (e.g., "jeandr.net")
        network: Network name ("homelab" or "lan")
        
    Returns:
        Success message
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Verify zone exists in config
    zones = get_dns_zones_from_config(network)
    zone = next((z for z in zones if z['name'] == zone_name), None)
    
    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone {zone_name} not found for network {network}"
        )
    
    # Get all records in this zone
    records = get_dns_records_from_config(network, zone_name=zone_name)
    
    # Delete all records in the zone
    for record in records:
        try:
            update_dns_record_in_config(
                network=network,
                operation="delete",
                record_name=record['name'],
                record_type=record['type'],
                record_value=record['value'],
                record_comment=record.get('comment'),
                zone_name=zone_name
            )
        except ValueError as e:
            logger.warning(f"Error deleting record {record['name']}: {e}")
    
    # Write config and reload service
    await _write_dns_config_and_reload(
        db, network, username, "delete",
        {"zone_name": zone_name}
    )
    
    return {"message": f"Zone {zone_name} deleted successfully (all records removed)"}


@router.get("/zones/{zone_name}/records", response_model=List[DnsRecord])
async def get_zone_records(
    zone_name: str,
    network: str,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[DnsRecord]:
    """Get all records for a zone from config files
    
    Args:
        zone_name: Zone name (e.g., "jeandr.net")
        network: Network name ("homelab" or "lan")
        
    Returns:
        List of DNS records
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    cache_key = f"api:dns:records:{network}:{zone_name}"
    cached = await get_json(cache_key)
    if cached:
        return [DnsRecord.model_validate(r) for r in cached]
    
    records = get_dns_records_from_config(network, zone_name=zone_name)
    
    result = []
    for record_dict in records:
        # Convert to DnsRecord model (assigning temporary IDs)
        record_dict['id'] = hash(f"{network}:{zone_name}:{record_dict['name']}") % (2**31)
        record_dict['zone_id'] = hash(f"{network}:{zone_name}") % (2**31)  # Temporary zone_id
        result.append(DnsRecord.model_validate(record_dict))
    
    out = sorted(result, key=lambda r: (r.type, r.name))
    await set_json(cache_key, [r.model_dump(mode="json") for r in out], ttl=30)
    return out


@router.post("/zones/{zone_name}/records", response_model=DnsRecord)
async def create_record(
    zone_name: str,
    network: str,
    record: DnsRecordCreate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsRecord:
    """Create a new DNS record in a zone (writes to config file)
    
    Args:
        zone_name: Zone name (e.g., "jeandr.net")
        network: Network name ("homelab" or "lan")
        record: Record creation data
        
    Returns:
        Created record
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Verify zone exists in config
    zones = get_dns_zones_from_config(network)
    zone = next((z for z in zones if z['name'] == zone_name), None)
    if not zone:
        raise HTTPException(
            status_code=404,
            detail=f"Zone {zone_name} not found for network {network}"
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
    
    # Update config file
    try:
        update_dns_record_in_config(
            network=network,
            operation="add",
            record_name=record.name,
            record_type=record.type,
            record_value=record.value,
            record_comment=record.comment,
            zone_name=zone_name
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Write config and reload service, track history
    await _write_dns_config_and_reload(
        db, network, username, "create",
        {"record_name": record.name, "zone_name": zone_name}
    )
    
    # Return created record (read back from config)
    records = get_dns_records_from_config(network, zone_name=zone_name)
    created = next((r for r in records if r['name'] == record.name), None)
    if not created:
        raise HTTPException(status_code=500, detail="Record created but not found in config")
    
    # Convert to DnsRecord model
    created['id'] = hash(f"{network}:{zone_name}:{record.name}") % (2**31)
    created['zone_id'] = hash(f"{network}:{zone_name}") % (2**31)
    return DnsRecord.model_validate(created)


@router.get("/records/{record_name}", response_model=DnsRecord)
async def get_record(
    record_name: str,
    network: str,
    zone_name: str,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsRecord:
    """Get a specific DNS record by name from config files
    
    Args:
        record_name: Record name (hostname or wildcard)
        network: Network name ("homelab" or "lan")
        zone_name: Zone name (e.g., "jeandr.net")
        
    Returns:
        Record details
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    records = get_dns_records_from_config(network, zone_name=zone_name)
    record = next((r for r in records if r['name'] == record_name), None)
    
    if not record:
        raise HTTPException(
            status_code=404,
            detail=f"Record {record_name} not found in zone {zone_name} for network {network}"
        )
    
    # Convert to DnsRecord model (assigning temporary IDs)
    record['id'] = hash(f"{network}:{zone_name}:{record_name}") % (2**31)
    record['zone_id'] = hash(f"{network}:{zone_name}") % (2**31)
    return DnsRecord.model_validate(record)


@router.put("/records/{record_name}", response_model=DnsRecord)
async def update_record(
    record_name: str,
    network: str,
    zone_name: str,
    record_update: DnsRecordUpdate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DnsRecord:
    """Update a DNS record in config files
    
    Args:
        record_name: Record name (hostname or wildcard)
        network: Network name ("homelab" or "lan")
        zone_name: Zone name (e.g., "jeandr.net")
        record_update: Record update data
        
    Returns:
        Updated record
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Verify record exists in config
    records = get_dns_records_from_config(network, zone_name=zone_name)
    existing_record = next((r for r in records if r['name'] == record_name), None)
    
    if not existing_record:
        raise HTTPException(
            status_code=404,
            detail=f"Record {record_name} not found in zone {zone_name} for network {network}"
        )
    
    # Determine new values
    new_name = record_update.name if record_update.name is not None else record_name
    new_type = record_update.type if record_update.type is not None else existing_record['type']
    new_value = record_update.value if record_update.value is not None else existing_record['value']
    new_comment = record_update.comment if record_update.comment is not None else existing_record.get('comment', '')
    
    # Validate record type
    if new_type not in ['A', 'CNAME']:
        raise HTTPException(
            status_code=400,
            detail="Record type must be 'A' or 'CNAME'"
        )
    
    # Validate A record value (must be IP address)
    if new_type == 'A':
        import ipaddress
        try:
            ipaddress.IPv4Address(new_value)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="A record value must be a valid IPv4 address"
            )
    
    # If name changed, delete old and create new
    if new_name != record_name:
        # Delete old record
        update_dns_record_in_config(
            network=network,
            operation="delete",
            record_name=record_name,
            record_type=existing_record['type'],
            record_value=existing_record['value'],
            record_comment=existing_record.get('comment'),
            zone_name=zone_name
        )
        # Create new record
        update_dns_record_in_config(
            network=network,
            operation="add",
            record_name=new_name,
            record_type=new_type,
            record_value=new_value,
            record_comment=new_comment,
            zone_name=zone_name
        )
    else:
        # Update existing record
        update_dns_record_in_config(
            network=network,
            operation="update",
            record_name=record_name,
            record_type=new_type,
            record_value=new_value,
            record_comment=new_comment,
            zone_name=zone_name
        )
    
    # Write config and reload service, track history
    await _write_dns_config_and_reload(
        db, network, username, "update",
        {"record_name": new_name, "zone_name": zone_name}
    )
    
    # Return updated record (read back from config)
    records = get_dns_records_from_config(network, zone_name=zone_name)
    updated = next((r for r in records if r['name'] == new_name), None)
    if not updated:
        raise HTTPException(status_code=500, detail="Record not found after update")
    
    # Convert to DnsRecord model
    updated['id'] = hash(f"{network}:{zone_name}:{new_name}") % (2**31)
    updated['zone_id'] = hash(f"{network}:{zone_name}") % (2**31)
    return DnsRecord.model_validate(updated)


@router.delete("/records/{record_name}")
async def delete_record(
    record_name: str,
    network: str,
    zone_name: str,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Delete a DNS record from config files
    
    Args:
        record_name: Record name (hostname or wildcard)
        network: Network name ("homelab" or "lan")
        zone_name: Zone name (e.g., "jeandr.net")
        
    Returns:
        Success message
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Verify record exists in config
    records = get_dns_records_from_config(network, zone_name=zone_name)
    existing_record = next((r for r in records if r['name'] == record_name), None)
    
    if not existing_record:
        raise HTTPException(
            status_code=404,
            detail=f"Record {record_name} not found in zone {zone_name} for network {network}"
        )
    
    # Delete record from config
    try:
        update_dns_record_in_config(
            network=network,
            operation="delete",
            record_name=record_name,
            record_type=existing_record['type'],
            record_value=existing_record['value'],
            record_comment=existing_record.get('comment'),
            zone_name=zone_name
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Write config and reload service, track history
    await _write_dns_config_and_reload(
        db, network, username, "delete",
        {"record_name": record_name, "zone_name": zone_name}
    )
    
    return {"message": f"Record {record_name} deleted successfully"}


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
    """Revert DNS configuration to a previous state from history
    
    Reads config snapshot from history and writes all records to webui-dns.conf.
    Clears existing WebUI-managed records first, then restores from snapshot.
    
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
    
    # Get current WebUI-managed records to clear them
    current_records = get_dns_records_from_config(network)
    # Filter to only WebUI-managed records (those that would be in webui-dns.conf)
    # For now, we'll clear all and restore from snapshot
    
    # Clear existing WebUI records by getting all records and deleting them
    # We need to identify which records are WebUI-managed vs router-config.nix
    # For simplicity, we'll write all records from snapshot to webui-dns.conf
    # which will override router-config.nix
    
    # Restore records from snapshot to config files
    for zone_data in config_snapshot.get('zones', []):
        zone_name = zone_data['name']
        for record_data in zone_data.get('records', []):
            try:
                # Add or update record
                update_dns_record_in_config(
                    network=network,
                    operation="add",  # Will overwrite if exists
                    record_name=record_data['name'],
                    record_type=record_data['type'],
                    record_value=record_data['value'],
                    record_comment=record_data.get('comment', ''),
                    zone_name=zone_name
                )
            except ValueError:
                # If record exists, update it
                try:
                    update_dns_record_in_config(
                        network=network,
                        operation="update",
                        record_name=record_data['name'],
                        record_type=record_data['type'],
                        record_value=record_data['value'],
                        record_comment=record_data.get('comment', ''),
                        zone_name=zone_name
                    )
                except ValueError:
                    logger.warning(f"Could not restore record {record_data['name']}")
    
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
    """Sync DNS configuration from config files to dnsmasq config files
    
    Regenerates config from current config files (router-config.nix + webui-dns.conf)
    and writes it to ensure dnsmasq has the latest configuration.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        Success message
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    try:
        # Generate config from current files (router-config.nix + webui-dns.conf)
        config_content = await generate_dnsmasq_dns_config(network, db)
        write_dns_config(network, config_content)
        
        # Restart dnsmasq service (dnsmasq doesn't support reload)
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        _control_service_via_systemctl(service_name, "restart")
        
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
    """Regenerate DNS configuration from config files
    
    Since config files are now the source of truth, this endpoint simply
    regenerates the dnsmasq config from current config files and writes it.
    This is equivalent to sync-config but kept for API compatibility.
    
    Args:
        network: Network name ("homelab" or "lan")
        source: Source (kept for compatibility, but config is always read from files)
        
    Returns:
        Success message
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    try:
        # Simply regenerate and write config (same as sync-config)
        config_content = await generate_dnsmasq_dns_config(network, db)
        write_dns_config(network, config_content)
        
        # Restart dnsmasq service (dnsmasq doesn't support reload)
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        _control_service_via_systemctl(service_name, "restart")
        
        logger.info(f"DNS config regenerated from config files for network {network}")
        
        return {
            "message": f"DNS configuration regenerated from config files",
            "network": network,
            "source": source
        }
    except Exception as e:
        logger.error(f"Failed to regenerate DNS config for network {network}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to regenerate DNS config: {str(e)}"
        )


@router.get("/networks/{network}/settings")
async def get_dns_network_settings(
    network: str,
    username: str = Depends(get_current_user)
) -> DnsNetworkSettings:
    """Get DNS network settings (domain hosting mode)
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        DNS network settings including forward_unlisted option
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    try:
        # Parse the DNS Nix file to get current settings
        nix_config = parse_dns_nix_file(network)
        if not nix_config:
            # If file doesn't exist or can't be parsed, return defaults
            return DnsNetworkSettings(forward_unlisted=False)
        
        return DnsNetworkSettings(
            forward_unlisted=nix_config.get('forward_unlisted', False)
        )
    except Exception as e:
        logger.error(f"Failed to get DNS network settings for {network}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get DNS network settings: {str(e)}"
        )


@router.put("/networks/{network}/settings")
async def update_dns_network_settings(
    network: str,
    settings: DnsNetworkSettings,
    username: str = Depends(get_current_user)
) -> dict:
    """Update DNS network settings (domain hosting mode)
    
    Args:
        network: Network name ("homelab" or "lan")
        settings: DNS network settings to update
        
    Returns:
        Success message and updated settings
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    try:
        # Read current Nix config
        nix_config = parse_dns_nix_file(network) or {
            'a_records': {},
            'cname_records': {},
            'forward_unlisted': False
        }
        
        # Update forward_unlisted setting
        nix_config['forward_unlisted'] = settings.forward_unlisted
        
        # Write back to Nix file
        nix_formatted = format_nix_dict(nix_config, indent=0)
        write_dns_nix_config(network, nix_formatted)
        
        logger.info(f"Updated DNS network settings for {network}: forward_unlisted={settings.forward_unlisted}")
        
        # Restart dnsmasq service to apply the change
        # The preStart script will regenerate dnsmasq.conf with the new setting
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        try:
            _control_service_via_systemctl(service_name, "restart")
            logger.info(f"Restarted {service_name} to apply DNS network settings")
            message = f"DNS network settings updated and applied for {network}."
        except Exception as restart_error:
            logger.warning(f"Failed to restart {service_name}: {restart_error}")
            message = f"DNS network settings updated for {network}, but service restart failed. Manual restart may be required."
        
        return {
            "message": message,
            "network": network,
            "settings": settings.dict(),
            "service_restarted": True
        }
    except Exception as e:
        logger.error(f"Failed to update DNS network settings for {network}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update DNS network settings: {str(e)}"
        )


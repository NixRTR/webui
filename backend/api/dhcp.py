"""
DHCP management API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional
import subprocess
import logging
import socket
import os

from ..database import get_db, DhcpConfigHistoryDB
from ..models import (
    DhcpNetwork, DhcpNetworkCreate, DhcpNetworkUpdate,
    DhcpReservation, DhcpReservationCreate, DhcpReservationUpdate
)
from ..api.auth import get_current_user
from ..collectors.services import get_service_status
from ..utils.dnsmasq_dhcp import generate_dnsmasq_dhcp_config
from ..utils.config_writer import write_dhcp_config
from ..utils.config_reader import (
    get_dhcp_networks_from_config,
    get_dhcp_reservations_from_config
)
from ..utils.config_manager import update_dhcp_reservation_in_config
import json
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dhcp", tags=["dhcp"])

# Map network names to systemd service names
NETWORK_SERVICE_MAP = {
    'homelab': 'dnsmasq-homelab',
    'lan': 'dnsmasq-lan',
}


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


async def _save_dhcp_config_history(
    db: AsyncSession,
    network: str,
    change_type: str,
    changed_by: str,
    change_details: dict
) -> None:
    """Save DHCP configuration change to history
    
    Reads current config from files and saves snapshot to history database.
    
    Args:
        db: Database session
        network: Network name
        change_type: Type of change ("create", "update", "delete")
        changed_by: Username who made the change
        change_details: Additional details about the change
    """
    # Get current DHCP configuration snapshot from config files
    networks = get_dhcp_networks_from_config()
    dhcp_network = next((n for n in networks if n['network'] == network), None)
    reservations = get_dhcp_reservations_from_config(network)
    
    # Build config snapshot
    config_snapshot = {
        'network': None,
        'reservations': []
    }
    
    if dhcp_network:
        config_snapshot['network'] = {
            'network': dhcp_network['network'],
            'enabled': dhcp_network.get('enabled', True),
            'start': dhcp_network.get('start', ''),
            'end': dhcp_network.get('end', ''),
            'lease_time': dhcp_network.get('lease_time', '1h'),
            'dns_servers': dhcp_network.get('dns_servers', []),
            'dynamic_domain': dhcp_network.get('dynamic_domain', ''),
        }
        
        for reservation in reservations:
            config_snapshot['reservations'].append({
                'hostname': reservation['hostname'],
                'hw_address': reservation['hw_address'],
                'ip_address': reservation['ip_address'],
                'comment': reservation.get('comment', ''),
                'enabled': reservation.get('enabled', True),
            })
    
    # Save to history
    history = DhcpConfigHistoryDB(
        network=network,
        change_type=change_type,
        changed_by=changed_by,
        config_snapshot=config_snapshot,
        change_details=change_details
    )
    db.add(history)
    await db.commit()


async def _write_dhcp_config_and_reload(
    db: AsyncSession,
    network: str,
    changed_by: str,
    change_type: str,
    change_details: dict
) -> None:
    """Generate DHCP config from files, write it, and restart dnsmasq service
    
    Args:
        db: Database session (for history tracking only)
        network: Network name
        changed_by: Username who made the change
        change_type: Type of change
        change_details: Additional details about the change
    """
    try:
        # Save history (before writing, to capture current state)
        await _save_dhcp_config_history(db, network, change_type, changed_by, change_details)
        
        # Generate config from files (router-config.nix + webui-dhcp.conf)
        config_content = generate_dnsmasq_dhcp_config(network)
        
        # Write config via helper service (can be None if DHCP disabled)
        if config_content:
            write_dhcp_config(network, config_content)
        else:
            # DHCP disabled - write empty file
            write_dhcp_config(network, "# DHCP disabled\n")
        
        # Restart dnsmasq service (dnsmasq doesn't support reload)
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        _control_service_via_systemctl(service_name, "restart")
        
        logger.info(f"DHCP config written and service restarted for network {network}")
    except Exception as e:
        logger.error(f"Failed to write DHCP config for network {network}: {e}", exc_info=True)
        # Don't raise - allow the API call to succeed even if config write fails


@router.get("/networks", response_model=List[DhcpNetwork])
async def get_networks(
    network: Optional[str] = None,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[DhcpNetwork]:
    """Get list of DHCP networks from config files (source of truth)
    
    Args:
        network: Optional filter by network ("homelab" or "lan")
        
    Returns:
        List of DHCP networks
    """
    networks = get_dhcp_networks_from_config()
    
    if network:
        if network not in ['homelab', 'lan']:
            raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
        networks = [n for n in networks if n['network'] == network]
    
    # Convert to Pydantic models (assigning temporary IDs for API compatibility)
    result_networks = []
    for net in networks:
        net_dict = {
            'id': hash(f"dhcp:{net['network']}") % (2**31),  # Temporary ID
            'network': net['network'],
            'enabled': net.get('enabled', True),
            'start': net.get('start', ''),
            'end': net.get('end', ''),
            'lease_time': net.get('lease_time', '1h'),
            'dns_servers': net.get('dns_servers', []),
            'dynamic_domain': net.get('dynamic_domain', ''),
            'original_config_path': None,
            'created_at': None,
            'updated_at': None,
        }
        result_networks.append(DhcpNetwork.model_validate(net_dict))
    
    return result_networks


@router.post("/networks", response_model=DhcpNetwork)
async def create_network(
    network: DhcpNetworkCreate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpNetwork:
    """Create a new DHCP network (not supported - networks come from router-config.nix)
    
    DHCP networks are defined in router-config.nix and cannot be created via WebUI.
    Only reservations can be managed through the WebUI.
    
    Args:
        network: Network creation data
        
    Returns:
        Error response
    """
    raise HTTPException(
        status_code=400,
        detail="DHCP networks cannot be created via WebUI. They must be defined in router-config.nix. Only reservations can be managed through the WebUI."
    )


@router.get("/networks/{network}", response_model=DhcpNetwork)
async def get_network(
    network: str,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpNetwork:
    """Get a specific DHCP network by name from config files
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        DHCP network
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    networks = get_dhcp_networks_from_config()
    dhcp_network = next((n for n in networks if n['network'] == network), None)
    
    if not dhcp_network:
        raise HTTPException(status_code=404, detail=f"DHCP network {network} not found")
    
    # Convert to Pydantic model (assigning temporary ID for API compatibility)
    net_dict = {
        'id': hash(f"dhcp:{network}") % (2**31),  # Temporary ID
        'network': dhcp_network['network'],
        'enabled': dhcp_network.get('enabled', True),
        'start': dhcp_network.get('start', ''),
        'end': dhcp_network.get('end', ''),
        'lease_time': dhcp_network.get('lease_time', '1h'),
        'dns_servers': dhcp_network.get('dns_servers', []),
        'dynamic_domain': dhcp_network.get('dynamic_domain', ''),
        'original_config_path': None,
        'created_at': None,
        'updated_at': None,
    }
    return DhcpNetwork.model_validate(net_dict)


@router.put("/networks/{network}", response_model=DhcpNetwork)
async def update_network(
    network: str,
    network_update: DhcpNetworkUpdate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpNetwork:
    """Update a DHCP network (not supported - networks come from router-config.nix)
    
    DHCP network settings (start, end, lease_time, etc.) are defined in router-config.nix
    and cannot be modified via WebUI. Only reservations can be managed through the WebUI.
    
    Args:
        network: Network name ("homelab" or "lan")
        network_update: Update data
        
    Returns:
        Error response
    """
    raise HTTPException(
        status_code=400,
        detail="DHCP network settings cannot be modified via WebUI. They must be changed in router-config.nix. Only reservations can be managed through the WebUI."
    )


@router.delete("/networks/{network}")
async def delete_network(
    network: str,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a DHCP network (not supported - networks come from router-config.nix)
    
    DHCP networks are defined in router-config.nix and cannot be deleted via WebUI.
    Only reservations can be managed through the WebUI.
    
    Args:
        network: Network name ("homelab" or "lan")
    """
    raise HTTPException(
        status_code=400,
        detail="DHCP networks cannot be deleted via WebUI. They must be removed from router-config.nix. Only reservations can be managed through the WebUI."
    )


@router.get("/networks/{network}/reservations", response_model=List[DhcpReservation])
async def get_reservations(
    network: str,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[DhcpReservation]:
    """Get list of DHCP reservations for a network from config files
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        List of DHCP reservations
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    reservations = get_dhcp_reservations_from_config(network)
    
    # Convert to Pydantic models (assigning temporary IDs for API compatibility)
    result_reservations = []
    for res in reservations:
        res_dict = {
            'id': hash(f"{network}:{res['hw_address']}") % (2**31),  # Temporary ID
            'network_id': hash(f"dhcp:{network}") % (2**31),  # Temporary network_id
            'hostname': res['hostname'],
            'hw_address': res['hw_address'],
            'ip_address': res['ip_address'],
            'comment': res.get('comment', ''),
            'enabled': res.get('enabled', True),
            'original_config_path': None,
            'created_at': None,
            'updated_at': None,
        }
        result_reservations.append(DhcpReservation.model_validate(res_dict))
    
    return sorted(result_reservations, key=lambda r: r.hostname)


@router.post("/networks/{network}/reservations", response_model=DhcpReservation)
async def create_reservation(
    network: str,
    reservation: DhcpReservationCreate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpReservation:
    """Create a new DHCP reservation (writes to config file)
    
    Args:
        network: Network name ("homelab" or "lan")
        reservation: Reservation creation data
        
    Returns:
        Created reservation
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Verify network exists in config
    networks = get_dhcp_networks_from_config()
    dhcp_network = next((n for n in networks if n['network'] == network), None)
    if not dhcp_network:
        raise HTTPException(status_code=404, detail=f"DHCP network {network} not found")
    
    # Check if reservation with same MAC already exists
    existing_reservations = get_dhcp_reservations_from_config(network)
    if any(r['hw_address'] == reservation.hw_address for r in existing_reservations):
        raise HTTPException(
            status_code=400,
            detail=f"Reservation with MAC {reservation.hw_address} already exists for network {network}"
        )
    
    # Check if IP address is already reserved
    if any(r['ip_address'] == reservation.ip_address for r in existing_reservations):
        raise HTTPException(
            status_code=400,
            detail=f"IP address {reservation.ip_address} is already reserved in network {network}"
        )
    
    # Update config file
    try:
        update_dhcp_reservation_in_config(
            network=network,
            operation="add",
            hw_address=reservation.hw_address,
            hostname=reservation.hostname,
            ip_address=reservation.ip_address,
            comment=reservation.comment
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Write config and reload service, track history
    await _write_dhcp_config_and_reload(
        db, network, username, "create",
        {"hostname": reservation.hostname, "hw_address": reservation.hw_address}
    )
    
    # Return created reservation (read back from config)
    reservations = get_dhcp_reservations_from_config(network)
    created = next((r for r in reservations if r['hw_address'] == reservation.hw_address), None)
    if not created:
        raise HTTPException(status_code=500, detail="Reservation created but not found in config")
    
    # Convert to DhcpReservation model
    created['id'] = hash(f"{network}:{reservation.hw_address}") % (2**31)
    created['network_id'] = hash(f"dhcp:{network}") % (2**31)
    return DhcpReservation.model_validate(created)


@router.get("/reservations/{hw_address}", response_model=DhcpReservation)
async def get_reservation(
    hw_address: str,
    network: str,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpReservation:
    """Get a specific DHCP reservation by MAC address from config files
    
    Args:
        hw_address: MAC address (hardware address)
        network: Network name ("homelab" or "lan")
        
    Returns:
        DHCP reservation
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    reservations = get_dhcp_reservations_from_config(network)
    reservation = next((r for r in reservations if r['hw_address'] == hw_address), None)
    
    if not reservation:
        raise HTTPException(
            status_code=404,
            detail=f"Reservation with MAC {hw_address} not found for network {network}"
        )
    
    # Convert to DhcpReservation model (assigning temporary IDs)
    reservation['id'] = hash(f"{network}:{hw_address}") % (2**31)
    reservation['network_id'] = hash(f"dhcp:{network}") % (2**31)
    return DhcpReservation.model_validate(reservation)


@router.put("/reservations/{hw_address}", response_model=DhcpReservation)
async def update_reservation(
    hw_address: str,
    network: str,
    reservation_update: DhcpReservationUpdate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpReservation:
    """Update a DHCP reservation in config files
    
    Args:
        hw_address: MAC address (hardware address)
        network: Network name ("homelab" or "lan")
        reservation_update: Update data
        
    Returns:
        Updated reservation
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Verify reservation exists in config
    reservations = get_dhcp_reservations_from_config(network)
    existing_reservation = next((r for r in reservations if r['hw_address'] == hw_address), None)
    
    if not existing_reservation:
        raise HTTPException(
            status_code=404,
            detail=f"Reservation with MAC {hw_address} not found for network {network}"
        )
    
    # Determine new values
    new_hw_address = reservation_update.hw_address if reservation_update.hw_address is not None else hw_address
    new_hostname = reservation_update.hostname if reservation_update.hostname is not None else existing_reservation['hostname']
    new_ip_address = reservation_update.ip_address if reservation_update.ip_address is not None else existing_reservation['ip_address']
    new_comment = reservation_update.comment if reservation_update.comment is not None else existing_reservation.get('comment', '')
    
    # Check for conflicts if MAC or IP is being changed
    if new_hw_address != hw_address:
        if any(r['hw_address'] == new_hw_address for r in reservations):
            raise HTTPException(
                status_code=400,
                detail=f"MAC address {new_hw_address} already reserved in network {network}"
            )
    
    if new_ip_address != existing_reservation['ip_address']:
        if any(r['ip_address'] == new_ip_address for r in reservations):
            raise HTTPException(
                status_code=400,
                detail=f"IP address {new_ip_address} already reserved in network {network}"
            )
    
    # If MAC address changed, delete old and create new
    if new_hw_address != hw_address:
        # Delete old reservation
        update_dhcp_reservation_in_config(
            network=network,
            operation="delete",
            hw_address=hw_address
        )
        # Create new reservation
        update_dhcp_reservation_in_config(
            network=network,
            operation="add",
            hw_address=new_hw_address,
            hostname=new_hostname,
            ip_address=new_ip_address,
            comment=new_comment
        )
    else:
        # Update existing reservation
        update_dhcp_reservation_in_config(
            network=network,
            operation="update",
            hw_address=hw_address,
            hostname=new_hostname,
            ip_address=new_ip_address,
            comment=new_comment
        )
    
    # Write config and reload service, track history
    await _write_dhcp_config_and_reload(
        db, network, username, "update",
        {"hw_address": new_hw_address, "hostname": new_hostname}
    )
    
    # Return updated reservation (read back from config)
    reservations = get_dhcp_reservations_from_config(network)
    updated = next((r for r in reservations if r['hw_address'] == new_hw_address), None)
    if not updated:
        raise HTTPException(status_code=500, detail="Reservation not found after update")
    
    # Convert to DhcpReservation model
    updated['id'] = hash(f"{network}:{new_hw_address}") % (2**31)
    updated['network_id'] = hash(f"dhcp:{network}") % (2**31)
    return DhcpReservation.model_validate(updated)


@router.delete("/reservations/{hw_address}")
async def delete_reservation(
    hw_address: str,
    network: str,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a DHCP reservation from config files
    
    Args:
        hw_address: MAC address (hardware address)
        network: Network name ("homelab" or "lan")
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    # Verify reservation exists in config
    reservations = get_dhcp_reservations_from_config(network)
    existing_reservation = next((r for r in reservations if r['hw_address'] == hw_address), None)
    
    if not existing_reservation:
        raise HTTPException(
            status_code=404,
            detail=f"Reservation with MAC {hw_address} not found for network {network}"
        )
    
    # Delete reservation from config
    try:
        update_dhcp_reservation_in_config(
            network=network,
            operation="delete",
            hw_address=hw_address
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    # Write config and reload service, track history
    await _write_dhcp_config_and_reload(
        db, network, username, "delete",
        {"hw_address": hw_address, "hostname": existing_reservation['hostname']}
    )
    
    return {"message": "DHCP reservation deleted"}


@router.get("/service-status/{network}")
async def get_dhcp_service_status(
    network: str,
    _: str = Depends(get_current_user)
):
    """Get DHCP service status for a network
    
    Uses systemctl to retrieve status (same approach as other services).
    Reading status doesn't require sudo, only control operations do.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        Service status information
    """
    if network not in NETWORK_SERVICE_MAP:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    service_name = NETWORK_SERVICE_MAP[network]
    status = get_service_status(service_name)
    
    if status is None:
        return {
            "service_name": service_name,
            "network": network,
            "is_active": False,
            "is_enabled": False,
            "exists": False
        }
    
    return {
        "service_name": service_name,
        "network": network,
        "is_active": status.is_active,
        "is_enabled": status.is_enabled,
        "exists": True,
        "pid": status.pid,
        "memory_mb": status.memory_mb,
        "cpu_percent": status.cpu_percent
    }


@router.post("/service/{network}/{action}")
async def control_dhcp_service(
    network: str,
    action: str,
    _: str = Depends(get_current_user)
):
    """Control DHCP service for a network
    
    Args:
        network: Network name ("homelab" or "lan")
        action: Action to perform ("start", "stop", "restart", "reload")
        
    Returns:
        Success message
    """
    if network not in NETWORK_SERVICE_MAP:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    if action not in ['start', 'stop', 'restart', 'reload']:
        logger.warning(f"Invalid action requested: {action}")
        raise HTTPException(status_code=400, detail="Action must be 'start', 'stop', 'restart', or 'reload'")
    
    service_name = NETWORK_SERVICE_MAP[network]
    full_service_name = f"{service_name}.service"
    
    try:
        # Use socket-based service control
        _control_service_via_systemctl(full_service_name, action)
        logger.info(f"Successfully {action}ed service {service_name}")
        
        return {
            "message": f"Service {service_name} {action}ed successfully",
            "action": action,
            "service_name": service_name,
            "network": network
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
async def revert_dhcp_config(
    network: str,
    history_id: int,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Revert DHCP configuration to a previous state from history
    
    Reads config snapshot from history and writes all reservations to webui-dhcp.conf.
    Clears existing WebUI-managed reservations first, then restores from snapshot.
    Note: Network settings are not restored as they come from router-config.nix.
    
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
        select(DhcpConfigHistoryDB)
        .where(
            DhcpConfigHistoryDB.id == history_id,
            DhcpConfigHistoryDB.network == network
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
    
    # Restore reservations from snapshot to config files
    # Note: Network settings are not restored as they come from router-config.nix
    for res_data in config_snapshot.get('reservations', []):
        try:
            # Add or update reservation
            update_dhcp_reservation_in_config(
                network=network,
                operation="add",  # Will overwrite if exists
                hw_address=res_data['hw_address'],
                hostname=res_data['hostname'],
                ip_address=res_data['ip_address'],
                comment=res_data.get('comment', '')
            )
        except ValueError:
            # If reservation exists, update it
            try:
                update_dhcp_reservation_in_config(
                    network=network,
                    operation="update",
                    hw_address=res_data['hw_address'],
                    hostname=res_data['hostname'],
                    ip_address=res_data['ip_address'],
                    comment=res_data.get('comment', '')
                )
            except ValueError:
                logger.warning(f"Could not restore reservation {res_data['hw_address']}")
    
    # Mark history record as reverted
    history.status = 'reverted'
    history.reverted_by = username
    history.reverted_at = datetime.utcnow()
    await db.commit()
    
    # Write config and reload service
    await _write_dhcp_config_and_reload(
        db, network, username, "revert",
        {"history_id": history_id, "reverted_from": history.change_type}
    )
    
    return {
        "message": f"DHCP configuration reverted to history record {history_id}",
        "network": network,
        "history_id": history_id
    }


@router.post("/sync-config/{network}")
async def sync_dhcp_config(
    network: str,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Sync DHCP configuration from config files to dnsmasq config files
    
    Regenerates config from current config files (router-config.nix + webui-dhcp.conf)
    and writes it to ensure dnsmasq has the latest configuration.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        Success message
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    try:
        # Generate config from current files (router-config.nix + webui-dhcp.conf)
        config_content = generate_dnsmasq_dhcp_config(network)
        if config_content:
            write_dhcp_config(network, config_content)
        else:
            # DHCP disabled - write empty file
            write_dhcp_config(network, "# DHCP disabled\n")
        
        # Restart dnsmasq service (dnsmasq doesn't support reload)
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        _control_service_via_systemctl(service_name, "restart")
        
        logger.info(f"DHCP config synced for network {network}")
        
        return {
            "message": f"DHCP configuration synced for network {network}",
            "network": network
        }
    except Exception as e:
        logger.error(f"Failed to sync DHCP config for network {network}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to sync DHCP config: {str(e)}"
        )


@router.post("/import-from-config/{network}")
async def import_dhcp_from_config(
    network: str,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """Regenerate DHCP configuration from config files
    
    Since config files are now the source of truth, this endpoint simply
    regenerates the dnsmasq config from current config files and writes it.
    This is equivalent to sync-config but kept for API compatibility.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        Success message
    """
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
    
    try:
        # Simply regenerate and write config (same as sync-config)
        config_content = generate_dnsmasq_dhcp_config(network)
        if config_content:
            write_dhcp_config(network, config_content)
        else:
            # DHCP disabled - write empty file
            write_dhcp_config(network, "# DHCP disabled\n")
        
        # Restart dnsmasq service (dnsmasq doesn't support reload)
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        _control_service_via_systemctl(service_name, "restart")
        
        logger.info(f"DHCP config regenerated from config files for network {network}")
        
        return {
            "message": f"DHCP configuration regenerated from config files",
            "network": network
        }
    except Exception as e:
        logger.error(f"Failed to regenerate DHCP config for network {network}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to regenerate DHCP config: {str(e)}"
        )


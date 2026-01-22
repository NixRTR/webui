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

from ..database import get_db, DhcpNetworkDB, DhcpReservationDB, DhcpConfigHistoryDB
from sqlalchemy import select
from ..models import (
    DhcpNetwork, DhcpNetworkCreate, DhcpNetworkUpdate,
    DhcpReservation, DhcpReservationCreate, DhcpReservationUpdate
)
from ..api.auth import get_current_user
from ..collectors.services import get_service_status
from ..utils.dnsmasq_dhcp import generate_dnsmasq_dhcp_config
from ..utils.config_writer import write_dhcp_config
from datetime import datetime
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
    
    Args:
        db: Database session
        network: Network name
        change_type: Type of change ("create", "update", "delete")
        changed_by: Username who made the change
        change_details: Additional details about the change
    """
    # Get current DHCP configuration snapshot
    result = await db.execute(
        select(DhcpNetworkDB)
        .where(DhcpNetworkDB.network == network)
        .limit(1)
    )
    dhcp_network = result.scalar_one_or_none()
    
    # Build config snapshot
    config_snapshot = {
        'network': None,
        'reservations': []
    }
    
    if dhcp_network:
        config_snapshot['network'] = {
            'id': dhcp_network.id,
            'network': dhcp_network.network,
            'enabled': dhcp_network.enabled,
            'start': str(dhcp_network.start),
            'end': str(dhcp_network.end),
            'lease_time': dhcp_network.lease_time,
            'dns_servers': [str(ip) for ip in (dhcp_network.dns_servers or [])],
            'dynamic_domain': dhcp_network.dynamic_domain,
        }
        
        # Get reservations for this network
        result = await db.execute(
            select(DhcpReservationDB)
            .where(DhcpReservationDB.network_id == dhcp_network.id)
            .order_by(DhcpReservationDB.hostname)
        )
        reservations = result.scalars().all()
        
        for reservation in reservations:
            config_snapshot['reservations'].append({
                'id': reservation.id,
                'hostname': reservation.hostname,
                'hw_address': str(reservation.hw_address),
                'ip_address': str(reservation.ip_address),
                'comment': reservation.comment,
                'enabled': reservation.enabled,
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
    """Generate DHCP config, write it, and reload dnsmasq service
    
    Args:
        db: Database session
        network: Network name
        changed_by: Username who made the change
        change_type: Type of change
        change_details: Additional details about the change
    """
    try:
        # Save history
        await _save_dhcp_config_history(db, network, change_type, changed_by, change_details)
        
        # Generate config
        config_content = await generate_dnsmasq_dhcp_config(db, network)
        
        # Write config via helper service (can be None if DHCP disabled)
        if config_content:
            write_dhcp_config(network, config_content)
        else:
            # DHCP disabled - write empty file or delete existing
            write_dhcp_config(network, "# DHCP disabled\n")
        
        # Reload dnsmasq service
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        _control_service_via_systemctl(service_name, "reload")
        
        logger.info(f"DHCP config written and service reloaded for network {network}")
    except Exception as e:
        logger.error(f"Failed to write DHCP config for network {network}: {e}", exc_info=True)
        # Don't raise - allow the API call to succeed even if config write fails
        # The database change is already committed


@router.get("/networks", response_model=List[DhcpNetwork])
async def get_networks(
    network: Optional[str] = None,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[DhcpNetwork]:
    """Get list of DHCP networks
    
    Args:
        network: Optional filter by network ("homelab" or "lan")
        
    Returns:
        List of DHCP networks
    """
    query = select(DhcpNetworkDB)
    if network:
        if network not in ['homelab', 'lan']:
            raise HTTPException(status_code=400, detail="Network must be 'homelab' or 'lan'")
        query = query.where(DhcpNetworkDB.network == network)
    
    query = query.order_by(DhcpNetworkDB.network)
    result = await db.execute(query)
    networks = result.scalars().all()
    
    # Convert database models to Pydantic models, converting INET types to strings
    result_networks = []
    for net in networks:
        net_dict = {
            'id': net.id,
            'network': net.network,
            'enabled': net.enabled,
            'start': str(net.start) if net.start else '',
            'end': str(net.end) if net.end else '',
            'lease_time': net.lease_time,
            'dns_servers': [str(ip) for ip in net.dns_servers] if net.dns_servers else None,
            'dynamic_domain': net.dynamic_domain,
            'original_config_path': net.original_config_path,
            'created_at': net.created_at,
            'updated_at': net.updated_at,
        }
        result_networks.append(DhcpNetwork.model_validate(net_dict))
    
    return result_networks


@router.post("/networks", response_model=DhcpNetwork)
async def create_network(
    network: DhcpNetworkCreate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpNetwork:
    """Create a new DHCP network
    
    Args:
        network: Network creation data
        
    Returns:
        Created network
    """
    # Check if network already exists
    result = await db.execute(
        select(DhcpNetworkDB).where(
            DhcpNetworkDB.network == network.network
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"DHCP network {network.network} already exists"
        )
    
    db_network = DhcpNetworkDB(
        network=network.network,
        enabled=network.enabled,
        start=network.start,
        end=network.end,
        lease_time=network.lease_time,
        dns_servers=network.dns_servers,
        dynamic_domain=network.dynamic_domain,
        original_config_path=network.original_config_path
    )
    db.add(db_network)
    await db.commit()
    await db.refresh(db_network)
    
    # Write config and reload service
    await _write_dhcp_config_and_reload(
        db, network.network, username, "create",
        {"network_id": db_network.id, "network": network.network}
    )
    
    # Convert INET types to strings
    net_dict = {
        'id': db_network.id,
        'network': db_network.network,
        'enabled': db_network.enabled,
        'start': str(db_network.start) if db_network.start else '',
        'end': str(db_network.end) if db_network.end else '',
        'lease_time': db_network.lease_time,
        'dns_servers': [str(ip) for ip in db_network.dns_servers] if db_network.dns_servers else None,
        'dynamic_domain': db_network.dynamic_domain,
        'original_config_path': db_network.original_config_path,
        'created_at': db_network.created_at,
        'updated_at': db_network.updated_at,
    }
    return DhcpNetwork.model_validate(net_dict)


@router.get("/networks/{network_id}", response_model=DhcpNetwork)
async def get_network(
    network_id: int,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpNetwork:
    """Get a specific DHCP network by ID
    
    Args:
        network_id: Network ID
        
    Returns:
        DHCP network
    """
    result = await db.execute(
        select(DhcpNetworkDB).where(DhcpNetworkDB.id == network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="DHCP network not found")
    
    # Convert INET types to strings
    net_dict = {
        'id': network.id,
        'network': network.network,
        'enabled': network.enabled,
        'start': str(network.start) if network.start else '',
        'end': str(network.end) if network.end else '',
        'lease_time': network.lease_time,
        'dns_servers': [str(ip) for ip in network.dns_servers] if network.dns_servers else None,
        'dynamic_domain': network.dynamic_domain,
        'original_config_path': network.original_config_path,
        'created_at': network.created_at,
        'updated_at': network.updated_at,
    }
    return DhcpNetwork.model_validate(net_dict)


@router.put("/networks/{network_id}", response_model=DhcpNetwork)
async def update_network(
    network_id: int,
    network_update: DhcpNetworkUpdate,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpNetwork:
    """Update a DHCP network
    
    Args:
        network_id: Network ID
        network_update: Update data
        
    Returns:
        Updated network
    """
    result = await db.execute(
        select(DhcpNetworkDB).where(DhcpNetworkDB.id == network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="DHCP network not found")
    
    # Update fields
    update_data = network_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(network, field, value)
    
    await db.commit()
    await db.refresh(network)
    
    # Write config and reload service
    await _write_dhcp_config_and_reload(
        db, network.network, username, "update",
        {"network_id": network_id, "network": network.network}
    )
    
    # Convert INET types to strings
    net_dict = {
        'id': network.id,
        'network': network.network,
        'enabled': network.enabled,
        'start': str(network.start) if network.start else '',
        'end': str(network.end) if network.end else '',
        'lease_time': network.lease_time,
        'dns_servers': [str(ip) for ip in network.dns_servers] if network.dns_servers else None,
        'dynamic_domain': network.dynamic_domain,
        'original_config_path': network.original_config_path,
        'created_at': network.created_at,
        'updated_at': network.updated_at,
    }
    return DhcpNetwork.model_validate(net_dict)


@router.delete("/networks/{network_id}")
async def delete_network(
    network_id: int,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a DHCP network (cascades to reservations)
    
    Args:
        network_id: Network ID
    """
    result = await db.execute(
        select(DhcpNetworkDB).where(DhcpNetworkDB.id == network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="DHCP network not found")
    
    network_name = network.network
    await db.delete(network)
    await db.commit()
    
    # Write config and reload service
    await _write_dhcp_config_and_reload(
        db, network_name, username, "delete",
        {"network_id": network_id, "network": network_name}
    )
    
    return {"message": "DHCP network deleted"}


@router.get("/networks/{network_id}/reservations", response_model=List[DhcpReservation])
async def get_reservations(
    network_id: int,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> List[DhcpReservation]:
    """Get list of DHCP reservations for a network
    
    Args:
        network_id: Network ID
        
    Returns:
        List of DHCP reservations
    """
    # Verify network exists
    result = await db.execute(
        select(DhcpNetworkDB).where(DhcpNetworkDB.id == network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="DHCP network not found")
    
    result = await db.execute(
        select(DhcpReservationDB)
        .where(DhcpReservationDB.network_id == network_id)
        .order_by(DhcpReservationDB.hostname)
    )
    reservations = result.scalars().all()
    
    # Convert database models to Pydantic models, converting MACADDR and INET types to strings
    result_reservations = []
    for res in reservations:
        res_dict = {
            'id': res.id,
            'network_id': res.network_id,
            'hostname': res.hostname,
            'hw_address': str(res.hw_address) if res.hw_address else '',
            'ip_address': str(res.ip_address) if res.ip_address else '',
            'comment': res.comment,
            'enabled': res.enabled,
            'original_config_path': res.original_config_path,
            'created_at': res.created_at,
            'updated_at': res.updated_at,
        }
        result_reservations.append(DhcpReservation.model_validate(res_dict))
    
    return result_reservations


@router.post("/networks/{network_id}/reservations", response_model=DhcpReservation)
async def create_reservation(
    network_id: int,
    reservation: DhcpReservationCreate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpReservation:
    """Create a new DHCP reservation
    
    Args:
        network_id: Network ID
        reservation: Reservation creation data (network_id will be overridden)
        
    Returns:
        Created reservation
    """
    # Verify network exists
    result = await db.execute(
        select(DhcpNetworkDB).where(DhcpNetworkDB.id == network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="DHCP network not found")
    
    # Check if reservation with same MAC already exists in this network
    result = await db.execute(
        select(DhcpReservationDB).where(
            DhcpReservationDB.network_id == network_id,
            DhcpReservationDB.hw_address == reservation.hw_address
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Reservation with MAC {reservation.hw_address} already exists for this network"
        )
    
    # Check if IP address is already reserved in this network
    result = await db.execute(
        select(DhcpReservationDB).where(
            DhcpReservationDB.network_id == network_id,
            DhcpReservationDB.ip_address == reservation.ip_address
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"IP address {reservation.ip_address} is already reserved in this network"
        )
    
    db_reservation = DhcpReservationDB(
        network_id=network_id,
        hostname=reservation.hostname,
        hw_address=reservation.hw_address,
        ip_address=reservation.ip_address,
        comment=reservation.comment,
        enabled=reservation.enabled,
        original_config_path=reservation.original_config_path
    )
    db.add(db_reservation)
    await db.commit()
    await db.refresh(db_reservation)
    
    # Write config and reload service
    await _write_dhcp_config_and_reload(
        db, network.network, username, "create",
        {"reservation_id": db_reservation.id, "hostname": reservation.hostname, "network_id": network_id}
    )
    
    # Convert MACADDR and INET types to strings
    res_dict = {
        'id': db_reservation.id,
        'network_id': db_reservation.network_id,
        'hostname': db_reservation.hostname,
        'hw_address': str(db_reservation.hw_address) if db_reservation.hw_address else '',
        'ip_address': str(db_reservation.ip_address) if db_reservation.ip_address else '',
        'comment': db_reservation.comment,
        'enabled': db_reservation.enabled,
        'original_config_path': db_reservation.original_config_path,
        'created_at': db_reservation.created_at,
        'updated_at': db_reservation.updated_at,
    }
    return DhcpReservation.model_validate(res_dict)


@router.get("/reservations/{reservation_id}", response_model=DhcpReservation)
async def get_reservation(
    reservation_id: int,
    _: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpReservation:
    """Get a specific DHCP reservation by ID
    
    Args:
        reservation_id: Reservation ID
        
    Returns:
        DHCP reservation
    """
    result = await db.execute(
        select(DhcpReservationDB).where(DhcpReservationDB.id == reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="DHCP reservation not found")
    
    # Convert MACADDR and INET types to strings
    res_dict = {
        'id': reservation.id,
        'network_id': reservation.network_id,
        'hostname': reservation.hostname,
        'hw_address': str(reservation.hw_address) if reservation.hw_address else '',
        'ip_address': str(reservation.ip_address) if reservation.ip_address else '',
        'comment': reservation.comment,
        'enabled': reservation.enabled,
        'original_config_path': reservation.original_config_path,
        'created_at': reservation.created_at,
        'updated_at': reservation.updated_at,
    }
    return DhcpReservation.model_validate(res_dict)


@router.put("/reservations/{reservation_id}", response_model=DhcpReservation)
async def update_reservation(
    reservation_id: int,
    reservation_update: DhcpReservationUpdate,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> DhcpReservation:
    """Update a DHCP reservation
    
    Args:
        reservation_id: Reservation ID
        reservation_update: Update data
        
    Returns:
        Updated reservation
    """
    result = await db.execute(
        select(DhcpReservationDB).where(DhcpReservationDB.id == reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="DHCP reservation not found")
    
    # If network_id is being changed, verify new network exists
    if reservation_update.network_id is not None and reservation_update.network_id != reservation.network_id:
        result = await db.execute(
            select(DhcpNetworkDB).where(DhcpNetworkDB.id == reservation_update.network_id)
        )
        new_network = result.scalar_one_or_none()
        if not new_network:
            raise HTTPException(status_code=404, detail="Target DHCP network not found")
        
        # Check for conflicts in new network
        if reservation_update.hw_address:
            result = await db.execute(
                select(DhcpReservationDB).where(
                    DhcpReservationDB.network_id == reservation_update.network_id,
                    DhcpReservationDB.hw_address == reservation_update.hw_address,
                    DhcpReservationDB.id != reservation_id
                )
            )
            if result.scalar_one_or_none():
                raise HTTPException(
                    status_code=400,
                    detail=f"MAC address {reservation_update.hw_address} already reserved in target network"
                )
        
        if reservation_update.ip_address:
            result = await db.execute(
                select(DhcpReservationDB).where(
                    DhcpReservationDB.network_id == reservation_update.network_id,
                    DhcpReservationDB.ip_address == reservation_update.ip_address,
                    DhcpReservationDB.id != reservation_id
                )
            )
            if result.scalar_one_or_none():
                raise HTTPException(
                    status_code=400,
                    detail=f"IP address {reservation_update.ip_address} already reserved in target network"
                )
    
    # Check for conflicts in current network if MAC or IP is being updated
    if reservation_update.hw_address and reservation_update.hw_address != reservation.hw_address:
        result = await db.execute(
            select(DhcpReservationDB).where(
                DhcpReservationDB.network_id == reservation.network_id,
                DhcpReservationDB.hw_address == reservation_update.hw_address,
                DhcpReservationDB.id != reservation_id
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=f"MAC address {reservation_update.hw_address} already reserved in this network"
            )
    
    if reservation_update.ip_address and reservation_update.ip_address != reservation.ip_address:
        result = await db.execute(
            select(DhcpReservationDB).where(
                DhcpReservationDB.network_id == reservation.network_id,
                DhcpReservationDB.ip_address == reservation_update.ip_address,
                DhcpReservationDB.id != reservation_id
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(
                status_code=400,
                detail=f"IP address {reservation_update.ip_address} already reserved in this network"
            )
    
    # Get network to determine network name
    result = await db.execute(
        select(DhcpNetworkDB).where(DhcpNetworkDB.id == reservation.network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    # Store original network for config update
    original_network = network.network
    
    # Update fields
    update_data = reservation_update.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(reservation, field, value)
    
    # If network_id changed, get new network
    if reservation_update.network_id and reservation_update.network_id != reservation.network_id:
        result = await db.execute(
            select(DhcpNetworkDB).where(DhcpNetworkDB.id == reservation.network_id)
        )
        network = result.scalar_one_or_none()
        if network:
            original_network = network.network
    
    await db.commit()
    await db.refresh(reservation)
    
    # Write config and reload service (for both old and new network if changed)
    networks_to_update = {original_network}
    if reservation.network_id != reservation.network_id:
        result = await db.execute(
            select(DhcpNetworkDB).where(DhcpNetworkDB.id == reservation.network_id)
        )
        new_network = result.scalar_one_or_none()
        if new_network:
            networks_to_update.add(new_network.network)
    
    for net in networks_to_update:
        await _write_dhcp_config_and_reload(
            db, net, username, "update",
            {"reservation_id": reservation_id, "hostname": reservation.hostname, "network_id": reservation.network_id}
        )
    
    # Convert MACADDR and INET types to strings
    res_dict = {
        'id': reservation.id,
        'network_id': reservation.network_id,
        'hostname': reservation.hostname,
        'hw_address': str(reservation.hw_address) if reservation.hw_address else '',
        'ip_address': str(reservation.ip_address) if reservation.ip_address else '',
        'comment': reservation.comment,
        'enabled': reservation.enabled,
        'original_config_path': reservation.original_config_path,
        'created_at': reservation.created_at,
        'updated_at': reservation.updated_at,
    }
    return DhcpReservation.model_validate(res_dict)


@router.delete("/reservations/{reservation_id}")
async def delete_reservation(
    reservation_id: int,
    username: str = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a DHCP reservation
    
    Args:
        reservation_id: Reservation ID
    """
    result = await db.execute(
        select(DhcpReservationDB).where(DhcpReservationDB.id == reservation_id)
    )
    reservation = result.scalar_one_or_none()
    if not reservation:
        raise HTTPException(status_code=404, detail="DHCP reservation not found")
    
    # Get network before deleting
    result = await db.execute(
        select(DhcpNetworkDB).where(DhcpNetworkDB.id == reservation.network_id)
    )
    network = result.scalar_one_or_none()
    if not network:
        raise HTTPException(status_code=404, detail="Network not found")
    
    network_name = network.network
    hostname = reservation.hostname
    
    await db.delete(reservation)
    await db.commit()
    
    # Write config and reload service
    await _write_dhcp_config_and_reload(
        db, network_name, username, "delete",
        {"reservation_id": reservation_id, "hostname": hostname, "network_id": reservation.network_id}
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
    """Revert DHCP configuration to a previous state
    
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
    
    # Delete all existing network and reservations for this network
    result = await db.execute(
        select(DhcpNetworkDB).where(DhcpNetworkDB.network == network)
    )
    dhcp_network = result.scalar_one_or_none()
    if dhcp_network:
        await db.delete(dhcp_network)
    
    # Restore network from snapshot
    network_data = config_snapshot.get('network')
    if network_data:
        db_network = DhcpNetworkDB(
            id=network_data['id'],
            network=network,
            enabled=network_data['enabled'],
            start=network_data['start'],
            end=network_data['end'],
            lease_time=network_data['lease_time'],
            dns_servers=network_data.get('dns_servers'),
            dynamic_domain=network_data.get('dynamic_domain')
        )
        db.add(db_network)
        await db.flush()  # Flush to get network ID
        
        # Restore reservations
        for res_data in config_snapshot.get('reservations', []):
            db_reservation = DhcpReservationDB(
                id=res_data['id'],
                network_id=db_network.id,
                hostname=res_data['hostname'],
                hw_address=res_data['hw_address'],
                ip_address=res_data['ip_address'],
                comment=res_data.get('comment'),
                enabled=res_data['enabled']
            )
            db.add(db_reservation)
    
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
    """Sync DHCP configuration from database to dnsmasq config files
    
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
        config_content = await generate_dnsmasq_dhcp_config(db, network)
        if config_content:
            write_dhcp_config(network, config_content)
        else:
            # DHCP disabled - write empty file
            write_dhcp_config(network, "# DHCP disabled\n")
        
        # Reload dnsmasq service
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        _control_service_via_systemctl(service_name, "reload")
        
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


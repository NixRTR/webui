"""
Network devices API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Dict
from datetime import datetime
from pydantic import BaseModel
import subprocess
import logging
from sqlalchemy import select, or_
from sqlalchemy.sql import cast
from sqlalchemy.types import String
from sqlalchemy.ext.asyncio import AsyncSession
import os

from ..auth import get_current_user
from ..collectors.network_devices import discover_network_devices, get_device_count_by_network
from ..collectors.dhcp import parse_dnsmasq_leases, trigger_new_device_scans
from ..database import AsyncSessionLocal, DeviceOverrideDB, NetworkDeviceDB, DevicePortScanDB, DevicePortScanResultDB
from ..utils.redis_client import delete as redis_delete
from ..workers.port_scanner import queue_port_scan
import logging

logger = logging.getLogger(__name__)


def _is_ipv4(ip: str) -> bool:
    """Check if an IP address is IPv4"""
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        for part in parts:
            num = int(part)
            if num < 0 or num > 255:
                return False
        return True
    except (ValueError, AttributeError):
        return False


router = APIRouter(prefix="/api/devices", tags=["devices"])


class NetworkDevice(BaseModel):
    """Network device information"""
    network: str
    ip_address: str
    mac_address: str
    hostname: str
    vendor: str | None = None
    is_dhcp: bool
    is_static: bool
    is_online: bool
    last_seen: datetime
    nickname: Optional[str] = None
    favorite: bool = False


class DeviceCounts(BaseModel):
    """Device counts by network"""
    network: str
    total: int
    online: int
    dhcp: int
    static: int


@router.get("/all")
async def get_all_devices(
    _: str = Depends(get_current_user)
) -> List[NetworkDevice]:
    """Get all discovered network devices
    
    Returns devices from:
    - ARP table (currently active)
    - DHCP leases (known clients)
    - Database (historical offline devices)
    
    Returns:
        List[NetworkDevice]: All discovered devices
    """
    dhcp_leases = parse_dnsmasq_leases()
    devices = discover_network_devices(dhcp_leases)

    # Trigger port scans for newly discovered devices from DHCP leases
    try:
        await trigger_new_device_scans(dhcp_leases)
    except Exception as e:
        logger.warning(f"Failed to trigger new device scans from DHCP: {e}")

    # Filter to IPv4 only
    devices = [d for d in devices if _is_ipv4(d.ip_address)]
    
    # Create a set of MAC addresses we already have from discovery
    seen_macs = {d.mac_address.lower() for d in devices}
    
    # Also query database for offline devices that might not be in current discovery
    async with AsyncSessionLocal() as session:
        # Get all devices from database that are in bridge subnets
        # Use cast to string for LIKE comparison with INET type
        result = await session.execute(
            select(NetworkDeviceDB).where(
                or_(
                    cast(NetworkDeviceDB.ip_address, String).like('192.168.2.%'),
                    cast(NetworkDeviceDB.ip_address, String).like('192.168.3.%')
                )
            )
        )
        db_devices = result.scalars().all()
        
        # Add devices from database that we haven't seen yet
        for db_dev in db_devices:
            mac_lower = str(db_dev.mac_address).lower()
            # Only add if IPv4 and not already in discovered devices
            if _is_ipv4(str(db_dev.ip_address)) and mac_lower not in seen_macs:
                # Create a NetworkDevice from database entry
                from ..collectors.network_devices import NetworkDevice as ND
                device = ND(
                    network=db_dev.network,
                    ip_address=str(db_dev.ip_address),
                    mac_address=str(db_dev.mac_address),
                    hostname=db_dev.hostname,
                    vendor=db_dev.vendor,
                    is_dhcp=db_dev.is_dhcp,
                    is_static=db_dev.is_static,
                    is_online=db_dev.is_online,
                    last_seen=db_dev.last_seen,
                )
                devices.append(device)
                seen_macs.add(mac_lower)

    # Load overrides for all MACs (with Redis caching)
    from ..utils.redis_client import get_json, set_json
    from ..config import settings
    
    cache_key = "device_overrides:all"
    cached_overrides = await get_json(cache_key)
    
    overrides: Dict[str, Dict] = {}
    if cached_overrides:
        # Use cached overrides directly as dict
        overrides = {mac.lower(): data for mac, data in cached_overrides.items()}
    else:
        # Cache miss - fetch from database
        async with AsyncSessionLocal() as session:
            # Fetch ALL overrides for caching
            result = await session.execute(select(DeviceOverrideDB))
            all_overrides = {}
            for ov in result.scalars().all():
                mac_key = str(ov.mac_address).lower()
                all_overrides[mac_key] = {
                    'nickname': ov.nickname,
                    'favorite': ov.favorite
                }
            
            # Cache all overrides
            if all_overrides:
                await set_json(cache_key, all_overrides, ttl=settings.redis_cache_ttl_overrides)
            
            # Populate overrides dict from database
            overrides = all_overrides

    enriched: List[NetworkDevice] = []
    for device in devices:
        key = device.mac_address.lower()
        ov = overrides.get(key)
        enriched.append(NetworkDevice(
            network=device.network,
            ip_address=device.ip_address,
            mac_address=device.mac_address,
            hostname=device.hostname,
            vendor=device.vendor,
            is_dhcp=device.is_dhcp,
            is_static=device.is_static,
            is_online=device.is_online,
            last_seen=device.last_seen,
            nickname=ov.get('nickname') if ov else None,
            favorite=ov.get('favorite', False) if ov else False,
        ))

    # Final deduplication by MAC address
    # If multiple devices have the same MAC, keep the one with:
    # 1. Most recent last_seen timestamp, OR
    # 2. If timestamps are equal, prefer online devices
    devices_by_mac: Dict[str, NetworkDevice] = {}
    for device in enriched:
        mac_lower = device.mac_address.lower()
        if mac_lower in devices_by_mac:
            existing = devices_by_mac[mac_lower]
            # Prefer device with more recent last_seen, or if equal, prefer online
            if (device.last_seen > existing.last_seen) or \
               (device.last_seen == existing.last_seen and device.is_online and not existing.is_online):
                devices_by_mac[mac_lower] = device
        else:
            devices_by_mac[mac_lower] = device
    
    # Convert back to list
    enriched = list(devices_by_mac.values())

    # Trigger port scans for newly discovered online devices
    from ..workers.port_scanner import queue_new_device_scan

    for device in enriched:
        if device.is_online:
            try:
                queued = await queue_new_device_scan(device.mac_address, device.ip_address)
                if queued:
                    logger.info(f"Queued scan for newly discovered device {device.mac_address}")
            except Exception as e:
                logger.warning(f"Failed to queue scan for new device {device.mac_address}: {e}")

    # Sort: favorites first, then by nickname/hostname
    enriched.sort(key=lambda d: (not d.favorite, (d.nickname or d.hostname or "").lower()))
    return enriched


@router.get("/counts")
async def get_device_counts(
    _: str = Depends(get_current_user)
) -> List[DeviceCounts]:
    """Get device counts by network
    
    Returns:
        List[DeviceCounts]: Device counts for each network
    """
    counts = get_device_count_by_network()
    
    result = []
    for network, data in counts.items():
        result.append(DeviceCounts(
            network=network,
            total=data['total'],
            online=data['online'],
            dhcp=data['dhcp'],
            static=data['total'] - data['dhcp']
        ))
    
    return result


@router.get("/by-network/{network}")
async def get_devices_by_network(
    network: str,
    _: str = Depends(get_current_user)
) -> List[NetworkDevice]:
    """Get devices for a specific network
    
    Args:
        network: Network name ('homelab' or 'lan')
        
    Returns:
        List[NetworkDevice]: Devices on the specified network
    """
    dhcp_leases = parse_dnsmasq_leases()
    all_devices = discover_network_devices(dhcp_leases)
    
    # Filter to IPv4 only and by network
    filtered = [d for d in all_devices if _is_ipv4(d.ip_address) and d.network == network]
    
    return [
        NetworkDevice(
            network=device.network,
            ip_address=device.ip_address,
            mac_address=device.mac_address,
            hostname=device.hostname,
            vendor=device.vendor,
            is_dhcp=device.is_dhcp,
            is_static=device.is_static,
            is_online=device.is_online,
            last_seen=device.last_seen
        )
        for device in filtered
    ]


class BlockRequest(BaseModel):
    """Request payload for blocking/unblocking a device"""
    ip_address: Optional[str] = None
    ip6_address: Optional[str] = None
    mac_address: Optional[str] = None


def _find_nft() -> str:
    # Prefer explicit env var (set by NixOS module to /nix/store/... path)
    env_path = os.environ.get("NFT_BIN")
    if env_path:
        return env_path
    candidates = [
        "/run/current-system/sw/bin/nft",
        "/usr/sbin/nft",
        "/sbin/nft",
        "nft",
    ]
    for path in candidates:
        try:
            p = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=2)
            if p.returncode == 0:
                return path
        except Exception:
            continue
    raise HTTPException(status_code=500, detail="nft binary not found")


def _run_nft(args: list[str]) -> None:
    nft = _find_nft()
    try:
        subprocess.run([nft] + args, check=True, capture_output=True, text=True, timeout=3)
    except subprocess.CalledProcessError as e:
        raise HTTPException(status_code=500, detail=f"nft failed: {e.stderr or e.stdout}")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="nft command not found")


logger = logging.getLogger(__name__)


@router.get("/blocked")
async def list_blocked(_: str = Depends(get_current_user)) -> dict:
    """List blocked devices from nft sets (IPs and MACs)"""
    
    result = {"ipv4": [], "ipv6": [], "macs": []}
    
    # Find nft binary
    try:
        nft_bin = _find_nft()
    except Exception as e:
        logger.error(f"Failed to find nft binary: {e}")
        return result
    
    # Helper function to parse nft set output
    def parse_nft_set_output(stdout: str) -> List[str]:
        """Parse nft list set output to extract elements"""
        items = []
        if not stdout:
            return items
        
        for line in stdout.splitlines():
            line = line.strip()
            # Handle both "elements = { ... }" and "elements = { ... }" formats
            if line.startswith("elements ="):
                try:
                    # Extract content between braces
                    if "{" in line and "}" in line:
                        inside = line.split("{", 1)[1].rsplit("}", 1)[0]
                        # Split by comma and clean up
                        items = [i.strip() for i in inside.split(",") if i.strip()]
                    break
                except Exception as e:
                    logger.warning(f"Failed to parse nft output line '{line}': {e}")
                    continue
        return items
    
    # Get IPv4 blocked addresses
    try:
        out_v4 = subprocess.run(
            [nft_bin, "list", "set", "inet", "router_block", "blocked_v4"],
            capture_output=True, text=True, timeout=2
        )
        if out_v4.returncode == 0:
            result["ipv4"] = parse_nft_set_output(out_v4.stdout)
            logger.debug(f"Found {len(result['ipv4'])} blocked IPv4 addresses")
        else:
            logger.warning(f"nft list set blocked_v4 failed with return code {out_v4.returncode}: {out_v4.stderr}")
    except Exception as e:
        logger.error(f"Exception while listing blocked IPv4 addresses: {e}", exc_info=True)
    
    # Get IPv6 blocked addresses
    try:
        out_v6 = subprocess.run(
            [nft_bin, "list", "set", "inet", "router_block", "blocked_v6"],
            capture_output=True, text=True, timeout=2
        )
        if out_v6.returncode == 0:
            result["ipv6"] = parse_nft_set_output(out_v6.stdout)
            logger.debug(f"Found {len(result['ipv6'])} blocked IPv6 addresses")
        else:
            logger.warning(f"nft list set blocked_v6 failed with return code {out_v6.returncode}: {out_v6.stderr}")
    except Exception as e:
        logger.error(f"Exception while listing blocked IPv6 addresses: {e}", exc_info=True)
    
    # Get blocked MAC addresses
    try:
        out_macs = subprocess.run(
            [nft_bin, "list", "set", "bridge", "router_block_mac", "blocked_macs"],
            capture_output=True, text=True, timeout=2
        )
        if out_macs.returncode == 0:
            mac_items = parse_nft_set_output(out_macs.stdout)
            result["macs"] = [m.lower() for m in mac_items]
            logger.debug(f"Found {len(result['macs'])} blocked MAC addresses")
        else:
            logger.warning(f"nft list set blocked_macs failed with return code {out_macs.returncode}: {out_macs.stderr}")
    except Exception as e:
        logger.error(f"Exception while listing blocked MAC addresses: {e}", exc_info=True)
    
    return result


@router.post("/block")
async def block_device(req: BlockRequest, _: str = Depends(get_current_user)) -> dict:
    """Block a device by adding MAC and/or IPs to nft sets"""
    if not any([req.ip_address, req.ip6_address, req.mac_address]):
        raise HTTPException(status_code=400, detail="Must supply mac_address or ip_address/ip6_address")

    if req.ip_address:
        _run_nft(["add", "element", "inet", "router_block", "blocked_v4", "{", req.ip_address, "}"])
    if req.ip6_address:
        _run_nft(["add", "element", "inet", "router_block", "blocked_v6", "{", req.ip6_address, "}"])
    if req.mac_address:
        _run_nft(["add", "element", "bridge", "router_block_mac", "blocked_macs", "{", req.mac_address.lower(), "}"])
    return {"status": "blocked", "ipv4": req.ip_address, "ipv6": req.ip6_address, "mac": req.mac_address}


@router.post("/unblock")
async def unblock_device(req: BlockRequest, _: str = Depends(get_current_user)) -> dict:
    """Unblock a device by removing MAC/IPs from nft sets"""
    if not any([req.ip_address, req.ip6_address, req.mac_address]):
        raise HTTPException(status_code=400, detail="Must supply mac_address or ip_address/ip6_address")

    if req.ip_address:
        _run_nft(["delete", "element", "inet", "router_block", "blocked_v4", "{", req.ip_address, "}"])
    if req.ip6_address:
        _run_nft(["delete", "element", "inet", "router_block", "blocked_v6", "{", req.ip6_address, "}"])
    if req.mac_address:
        _run_nft(["delete", "element", "bridge", "router_block_mac", "blocked_macs", "{", req.mac_address.lower(), "}"])
    return {"status": "unblocked", "ipv4": req.ip_address, "ipv6": req.ip6_address, "mac": req.mac_address}


class OverrideRequest(BaseModel):
    mac_address: str
    nickname: Optional[str] = None
    favorite: Optional[bool] = None


@router.get("/overrides")
async def list_overrides(_: str = Depends(get_current_user)) -> List[OverrideRequest]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DeviceOverrideDB))
        rows = result.scalars().all()
        return [OverrideRequest(mac_address=str(r.mac_address), nickname=r.nickname, favorite=r.favorite) for r in rows]


@router.post("/override")
async def upsert_override(req: OverrideRequest, _: str = Depends(get_current_user)) -> dict:
    if not req.mac_address:
        raise HTTPException(status_code=400, detail="mac_address is required")
    async with AsyncSessionLocal() as session:
        # Try find existing
        result = await session.execute(select(DeviceOverrideDB).where(DeviceOverrideDB.mac_address == req.mac_address))
        row = result.scalar_one_or_none()
        if row:
            if req.nickname is not None:
                row.nickname = req.nickname
            if req.favorite is not None:
                row.favorite = bool(req.favorite)
        else:
            row = DeviceOverrideDB(mac_address=req.mac_address, nickname=req.nickname, favorite=bool(req.favorite))
            session.add(row)
        await session.commit()
        # Invalidate device overrides cache
        await redis_delete("device_overrides:all")
        return {"status": "ok"}


@router.delete("/override/{mac}")
async def delete_override(mac: str, _: str = Depends(get_current_user)) -> dict:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DeviceOverrideDB).where(DeviceOverrideDB.mac_address == mac))
        row = result.scalar_one_or_none()
        if row:
            await session.delete(row)
            await session.commit()
        # Invalidate device overrides cache
        await redis_delete("device_overrides:all")
        return {"status": "ok"}


class PortInfo(BaseModel):
    """Port scan result information"""
    port: int
    state: str
    service_name: Optional[str] = None
    service_version: Optional[str] = None
    service_product: Optional[str] = None
    service_extrainfo: Optional[str] = None
    protocol: str


class PortScanResult(BaseModel):
    """Port scan result with metadata"""
    scan_id: int
    mac_address: str
    ip_address: str
    scan_status: str  # 'pending', 'in_progress', 'completed', 'failed'
    scan_started_at: datetime
    scan_completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    ports: List[PortInfo] = []


@router.get("/{mac_address}/ports")
async def get_device_port_scan(
    mac_address: str,
    _: str = Depends(get_current_user)
) -> PortScanResult:
    """Get latest port scan results for a device
    
    Args:
        mac_address: Device MAC address
        
    Returns:
        PortScanResult: Latest port scan results with port details
    """
    async with AsyncSessionLocal() as session:
        # Get the latest scan for this device
        result = await session.execute(
            select(DevicePortScanDB).where(
                DevicePortScanDB.mac_address == mac_address
            ).order_by(DevicePortScanDB.scan_started_at.desc())
        )
        scan_record = result.scalar_one_or_none()
        
        if not scan_record:
            raise HTTPException(status_code=404, detail="No port scan found for this device")
        
        # Get port scan results
        ports_result = await session.execute(
            select(DevicePortScanResultDB).where(
                DevicePortScanResultDB.scan_id == scan_record.id
            ).order_by(DevicePortScanResultDB.port)
        )
        port_records = ports_result.scalars().all()
        
        ports = [
            PortInfo(
                port=pr.port,
                state=pr.state,
                service_name=pr.service_name,
                service_version=pr.service_version,
                service_product=pr.service_product,
                service_extrainfo=pr.service_extrainfo,
                protocol=pr.protocol
            )
            for pr in port_records
        ]
        
        return PortScanResult(
            scan_id=scan_record.id,
            mac_address=str(scan_record.mac_address),
            ip_address=str(scan_record.ip_address),
            scan_status=scan_record.scan_status,
            scan_started_at=scan_record.scan_started_at,
            scan_completed_at=scan_record.scan_completed_at,
            error_message=scan_record.error_message,
            ports=ports
        )


@router.post("/{mac_address}/ports/scan")
async def trigger_device_port_scan(
    mac_address: str,
    _: str = Depends(get_current_user)
) -> dict:
    """Trigger an immediate port scan for a device
    
    Args:
        mac_address: Device MAC address
        
    Returns:
        dict: Status of scan request
    """
    # Get device IP address
    async with AsyncSessionLocal() as session:
        # Try to get IP from network_devices table
        device_result = await session.execute(
            select(NetworkDeviceDB).where(
                NetworkDeviceDB.mac_address == mac_address
            )
        )
        device = device_result.scalar_one_or_none()
        
        if not device:
            # Try to get from current discovery
            dhcp_leases = parse_dnsmasq_leases()
            devices = discover_network_devices(dhcp_leases)
            matching_device = next((d for d in devices if d.mac_address.lower() == mac_address.lower()), None)
            
            if not matching_device:
                raise HTTPException(status_code=404, detail="Device not found")
            
            ip_address = matching_device.ip_address
        else:
            ip_address = str(device.ip_address)
        
        # Check if scan is already in progress
        scan_result = await session.execute(
            select(DevicePortScanDB).where(
                DevicePortScanDB.mac_address == mac_address,
                DevicePortScanDB.scan_status.in_(['pending', 'in_progress'])
            )
        )
        existing_scan = scan_result.scalar_one_or_none()
        
        if existing_scan:
            return {
                "status": existing_scan.scan_status,
                "message": f"Scan already {existing_scan.scan_status}"
            }
        
        # Queue the scan
        queued = await queue_port_scan(mac_address, ip_address)
        
        if queued:
            return {
                "status": "queued",
                "message": "Port scan queued successfully"
            }
        else:
            return {
                "status": "skipped",
                "message": "Port scan already in progress or device offline"
            }


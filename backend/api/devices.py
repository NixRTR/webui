"""
Network devices API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List, Optional, Dict
from datetime import datetime, timezone
from pydantic import BaseModel
import subprocess
import logging
import time
from sqlalchemy import select, or_, func

logger = logging.getLogger(__name__)
from sqlalchemy.sql import cast
from sqlalchemy.types import String
from sqlalchemy.ext.asyncio import AsyncSession
import os

from ..auth import get_current_user
from ..collectors.network_devices import discover_network_devices, get_device_count_by_network
from ..collectors.dhcp import parse_dnsmasq_leases, trigger_new_device_scans
from ..database import AsyncSessionLocal, DeviceOverrideDB, NetworkDeviceDB, DevicePortScanDB, DevicePortScanResultDB
from ..utils.redis_client import delete as redis_delete, get_json, set_json
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
    """Network device information (hostname is effective: override if set, else discovery)"""
    network: str
    ip_address: str
    mac_address: str
    hostname: str
    vendor: str | None = None
    is_dhcp: bool
    is_static: bool
    is_online: bool
    last_seen: datetime
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
    # Check cache first to avoid expensive operations
    from ..utils.redis_client import get_json, set_json
    from ..config import settings
    import time
    
    overall_start = time.time()
    
    cache_key = "api:devices:all"
    cached_result = await get_json(cache_key)
    if cached_result:
        # Return cached result - FastAPI will serialize dicts to NetworkDevice models
        return cached_result
    
    # Cache DHCP leases parsing (expensive file I/O)
    # Use longer cache TTL since leases don't change frequently
    dhcp_start = time.time()
    dhcp_cache_key = "cache:dhcp_leases"
    cached_dhcp = await get_json(dhcp_cache_key)
    if cached_dhcp:
        from ..models import DHCPLease
        dhcp_leases = [DHCPLease(**lease) for lease in cached_dhcp]
    else:
        dhcp_leases = parse_dnsmasq_leases()
        # Cache for 15 seconds (DHCP leases change infrequently, longer cache reduces I/O)
        await set_json(dhcp_cache_key, [lease.model_dump() for lease in dhcp_leases], ttl=15)
    dhcp_time = time.time() - dhcp_start
    
    discovery_start = time.time()
    devices = discover_network_devices(dhcp_leases)
    discovery_time = time.time() - discovery_start
    
    if dhcp_time > 0.1 or discovery_time > 0.2:
        logger.warning(f"Slow device discovery: DHCP parsing={dhcp_time:.3f}s, discovery={discovery_time:.3f}s")

    # NOTE: Port scan triggering moved to background worker to avoid blocking API requests
    # This was causing high CPU usage when triggered on every request

    # Filter to IPv4 only
    devices = [d for d in devices if _is_ipv4(d.ip_address)]
    
    # Create a set of MAC addresses we already have from discovery
    seen_macs = {d.mac_address.lower() for d in devices}
    
    # Also query database for offline devices that might not be in current discovery
    # Only fetch devices seen recently (last 7 days) to avoid loading thousands of old devices
    # Use network column (indexed) instead of IP LIKE pattern for better performance
    from datetime import timedelta
    recent_cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    
    async with AsyncSessionLocal() as session:
        # Filter by network column (has index) instead of IP pattern matching
        # This is much more efficient than LIKE with cast()
        # Limit results to prevent loading too many devices
        query_start = time.time()
        result = await session.execute(
            select(NetworkDeviceDB).where(
                NetworkDeviceDB.network.in_(['homelab', 'lan']),
                NetworkDeviceDB.last_seen >= recent_cutoff
            ).limit(500)  # Limit to prevent excessive memory usage
        )
        db_devices = result.scalars().all()
        query_time = time.time() - query_start
        if query_time > 0.1:  # Log slow queries (>100ms)
            logger.warning(f"Slow database query in get_all_devices: {query_time:.3f}s (fetched {len(db_devices)} devices)")
        
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
            query_start = time.time()
            result = await session.execute(select(DeviceOverrideDB))
            override_rows = result.scalars().all()
            query_time = time.time() - query_start
            if query_time > 0.05:  # Log slow queries (>50ms)
                logger.warning(f"Slow DeviceOverrideDB query: {query_time:.3f}s (fetched {len(override_rows)} rows)")
            
            all_overrides = {}
            for ov in override_rows:
                mac_key = str(ov.mac_address).lower()
                all_overrides[mac_key] = {
                    'hostname': ov.hostname,
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
        override_hostname = (ov.get('hostname') or '').strip() if ov else None
        effective_hostname = override_hostname if override_hostname else (device.hostname or '')
        enriched.append(NetworkDevice(
            network=device.network,
            ip_address=device.ip_address,
            mac_address=device.mac_address,
            hostname=effective_hostname,
            vendor=device.vendor,
            is_dhcp=device.is_dhcp,
            is_static=device.is_static,
            is_online=device.is_online,
            last_seen=device.last_seen,
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

    # Sort: favorites first, then by hostname
    enriched.sort(key=lambda d: (not d.favorite, (d.hostname or "").lower()))

    # Cache the result for future requests
    cache_start = time.time()
    cache_data = [device.model_dump() for device in enriched]
    await set_json(cache_key, cache_data, ttl=settings.redis_cache_ttl_api)
    cache_time = time.time() - cache_start
    
    overall_time = time.time() - overall_start
    if overall_time > 0.5:  # Log if entire endpoint takes >500ms
        logger.warning(
            f"Slow get_all_devices endpoint: {overall_time:.3f}s total "
            f"(DHCP={dhcp_time:.3f}s, discovery={discovery_time:.3f}s, cache={cache_time:.3f}s, "
            f"devices={len(enriched)})"
        )
    
    # NOTE: Port scan triggering removed from hot path - causes high CPU usage
    # Port scans should be triggered by background workers or on-demand via separate endpoint
    
    # Return enriched devices as dicts (FastAPI will serialize to NetworkDevice models)
    return cache_data


@router.get("/counts")
async def get_device_counts(
    _: str = Depends(get_current_user)
) -> List[DeviceCounts]:
    """Get device counts by network
    
    Returns:
        List[DeviceCounts]: Device counts for each network
    """
    # Cache device counts to avoid expensive device discovery
    from ..utils.redis_client import get_json, set_json
    from ..config import settings
    
    cache_key = "api:devices:counts"
    cached_result = await get_json(cache_key)
    if cached_result:
        return [DeviceCounts(**item) for item in cached_result]
    
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
    
    # Cache for 30 seconds (counts don't change frequently)
    await set_json(cache_key, [item.model_dump() for item in result], ttl=30)
    
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
    # Reuse cached data from /api/devices/all to avoid duplicate expensive operations
    from ..utils.redis_client import get_json
    
    cache_key = "api:devices:all"
    cached_result = await get_json(cache_key)
    
    if cached_result:
        # Filter cached devices by network
        filtered = [d for d in cached_result if d.get('network') == network]
        return filtered
    
    # Fallback: if cache miss, do the expensive operation
    dhcp_leases = parse_dnsmasq_leases()
    all_devices = discover_network_devices(dhcp_leases)
    
    # Filter to IPv4 only and by network
    filtered_devices = [d for d in all_devices if _is_ipv4(d.ip_address) and d.network == network]
    
    # Convert to dict format for return (consistent with cached response)
    return [
        {
            'network': device.network,
            'ip_address': device.ip_address,
            'mac_address': device.mac_address,
            'hostname': device.hostname,
            'vendor': device.vendor,
            'is_dhcp': device.is_dhcp,
            'is_static': device.is_static,
            'is_online': device.is_online,
            'last_seen': device.last_seen,
            'favorite': False  # Default, will be enriched if needed
        }
        for device in filtered_devices
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
    hostname: Optional[str] = None
    favorite: Optional[bool] = None
    network: Optional[str] = None  # Required when setting hostname, for DHCP reservation sync
    ip_address: Optional[str] = None  # Optional; used when creating a new reservation


@router.get("/overrides")
async def list_overrides(_: str = Depends(get_current_user)) -> List[OverrideRequest]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DeviceOverrideDB))
        rows = result.scalars().all()
        return [OverrideRequest(mac_address=str(r.mac_address), hostname=r.hostname, favorite=r.favorite) for r in rows]


def _get_ip_for_mac_in_network(mac: str, network: str) -> Optional[str]:
    """Get current IP for a MAC in the given network (from leases or discovery)."""
    mac_lower = mac.strip().lower()
    leases = parse_dnsmasq_leases()
    for lease in leases:
        if lease.mac_address.lower() == mac_lower and lease.network == network:
            return lease.ip_address
    devices = discover_network_devices(leases)
    for d in devices:
        if d.mac_address.lower() == mac_lower and d.network == network:
            return d.ip_address
    return None


@router.post("/override")
async def upsert_override(req: OverrideRequest, username: str = Depends(get_current_user)) -> dict:
    if not req.mac_address:
        raise HTTPException(status_code=400, detail="mac_address is required")
    mac_normalized = req.mac_address.strip().lower()
    if req.hostname is not None and req.network:
        if req.network not in ('homelab', 'lan'):
            raise HTTPException(status_code=400, detail="network must be 'homelab' or 'lan'")
        from ..utils.config_reader import get_dhcp_reservations_from_config
        from ..utils.config_manager import update_dhcp_reservation_in_config
        from ..api.dhcp import _control_service_via_systemctl, NETWORK_SERVICE_MAP
        reservations = get_dhcp_reservations_from_config(req.network)
        existing = next((r for r in reservations if (r.get('hw_address') or '').lower() == mac_normalized), None)
        hostname_value = (req.hostname or '').strip()
        try:
            if existing:
                update_dhcp_reservation_in_config(
                    req.network, "update", mac_normalized,
                    hostname=hostname_value if hostname_value else existing.get('hostname'),
                    ip_address=existing.get('ip_address'),
                    comment=existing.get('comment') or ''
                )
            else:
                ip_address = req.ip_address or _get_ip_for_mac_in_network(req.mac_address, req.network)
                if not ip_address:
                    raise HTTPException(
                        status_code=400,
                        detail="No IP for this device on this network. Provide ip_address or ensure the device has a lease."
                    )
                update_dhcp_reservation_in_config(
                    req.network, "add", mac_normalized,
                    hostname=hostname_value or f"dhcp-{ip_address.split('.')[-1]}",
                    ip_address=ip_address
                )
            service_name = f"{NETWORK_SERVICE_MAP[req.network]}.service"
            _control_service_via_systemctl(service_name, "restart")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.warning(f"DHCP config update failed for %s: %s", req.mac_address, e, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to sync hostname to DHCP: {e}")
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(DeviceOverrideDB).where(DeviceOverrideDB.mac_address == req.mac_address))
        row = result.scalar_one_or_none()
        if row:
            if req.hostname is not None:
                row.hostname = (req.hostname or '').strip() or None
            if req.favorite is not None:
                row.favorite = bool(req.favorite)
            row.updated_at = datetime.now(timezone.utc)
        else:
            now = datetime.now(timezone.utc)
            row = DeviceOverrideDB(
                mac_address=req.mac_address,
                hostname=(req.hostname or '').strip() or None if req.hostname is not None else None,
                favorite=bool(req.favorite) if req.favorite is not None else False,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        await session.commit()
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


class IpHistoryEntry(BaseModel):
    """IP address seen for a device (MAC) with last seen time"""
    ip_address: str
    last_seen: datetime


@router.get("/by-mac/{mac_address}", response_model=NetworkDevice)
async def get_device_by_mac(
    mac_address: str,
    _: str = Depends(get_current_user)
) -> NetworkDevice:
    """Get a single device by MAC address (hardware identity).
    Returns current IP, hostname, network, etc. 404 if not found.
    """
    mac_lower = mac_address.lower()
    cache_key = f"api:devices:by_mac:{mac_lower}"
    cached = await get_json(cache_key)
    if cached:
        return NetworkDevice.model_validate(cached)

    dhcp_leases = parse_dnsmasq_leases()
    devices = discover_network_devices(dhcp_leases)
    devices = [d for d in devices if _is_ipv4(d.ip_address)]
    seen_macs = {d.mac_address.lower() for d in devices}

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(NetworkDeviceDB).where(
                or_(
                    cast(NetworkDeviceDB.ip_address, String).like('192.168.2.%'),
                    cast(NetworkDeviceDB.ip_address, String).like('192.168.3.%')
                )
            )
        )
        for db_dev in result.scalars().all():
            db_mac_lower = str(db_dev.mac_address).lower()
            if _is_ipv4(str(db_dev.ip_address)) and db_mac_lower not in seen_macs:
                from ..collectors.network_devices import NetworkDevice as ND
                devices.append(ND(
                    network=db_dev.network,
                    ip_address=str(db_dev.ip_address),
                    mac_address=str(db_dev.mac_address),
                    hostname=db_dev.hostname,
                    vendor=db_dev.vendor,
                    is_dhcp=db_dev.is_dhcp,
                    is_static=db_dev.is_static,
                    is_online=db_dev.is_online,
                    last_seen=db_dev.last_seen,
                ))
                seen_macs.add(db_mac_lower)

    from ..utils.redis_client import get_json, set_json
    from ..config import settings
    cache_key = "device_overrides:all"
    cached_overrides = await get_json(cache_key)
    overrides: Dict[str, Dict] = {}
    if cached_overrides:
        overrides = {m.lower(): data for m, data in cached_overrides.items()}
    else:
        async with AsyncSessionLocal() as session:
            result = await session.execute(select(DeviceOverrideDB))
            all_overrides = {
                str(ov.mac_address).lower(): {'hostname': ov.hostname, 'favorite': ov.favorite}
                for ov in result.scalars().all()
            }
            if all_overrides:
                await set_json(cache_key, all_overrides, ttl=settings.redis_cache_ttl_overrides)
            overrides = all_overrides

    devices_by_mac: Dict[str, NetworkDevice] = {}
    for device in devices:
        key = device.mac_address.lower()
        ov = overrides.get(key)
        override_hostname = (ov.get('hostname') or '').strip() if ov else None
        effective_hostname = override_hostname if override_hostname else (device.hostname or '')
        nd = NetworkDevice(
            network=device.network,
            ip_address=device.ip_address,
            mac_address=device.mac_address,
            hostname=effective_hostname,
            vendor=device.vendor,
            is_dhcp=device.is_dhcp,
            is_static=device.is_static,
            is_online=device.is_online,
            last_seen=device.last_seen,
            favorite=ov.get('favorite', False) if ov else False,
        )
        if key in devices_by_mac:
            existing = devices_by_mac[key]
            if (nd.last_seen > existing.last_seen) or (
                nd.last_seen == existing.last_seen and nd.is_online and not existing.is_online
            ):
                devices_by_mac[key] = nd
        else:
            devices_by_mac[key] = nd

    if mac_lower not in devices_by_mac:
        raise HTTPException(status_code=404, detail="Device not found")
    out = devices_by_mac[mac_lower]
    await set_json(cache_key, out.model_dump(mode="json"), ttl=30)
    return out


@router.get("/by-mac/{mac_address}/ip-history", response_model=List[IpHistoryEntry])
async def get_device_ip_history(
    mac_address: str,
    _: str = Depends(get_current_user)
) -> List[IpHistoryEntry]:
    """Get IP address history for a device (MAC). From port scan records."""
    mac_lower = mac_address.lower()
    cache_key = f"api:devices:ip_history:{mac_lower}"
    cached = await get_json(cache_key)
    if cached:
        return [IpHistoryEntry.model_validate(d) for d in cached]

    async with AsyncSessionLocal() as session:
        stmt = (
            select(
                DevicePortScanDB.ip_address,
                func.max(DevicePortScanDB.scan_started_at).label("last_seen"),
            )
            .where(DevicePortScanDB.mac_address == mac_address)
            .group_by(DevicePortScanDB.ip_address)
            .order_by(func.max(DevicePortScanDB.scan_started_at).desc())
            .limit(100)  # Limit to most recent 100 IP addresses
        )
        result = await session.execute(stmt)
        rows = result.all()
    out = [
        IpHistoryEntry(ip_address=str(r.ip_address), last_seen=r.last_seen)
        for r in rows
    ]
    await set_json(cache_key, [e.model_dump(mode="json") for e in out], ttl=60)
    return out


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
    mac_lower = mac_address.lower()
    cache_key = f"api:devices:ports:{mac_lower}"
    cached = await get_json(cache_key)
    if cached:
        return PortScanResult.model_validate(cached)

    async with AsyncSessionLocal() as session:
        # Get the latest scan for this device (limit 1 so scalar_one_or_none is valid)
        result = await session.execute(
            select(DevicePortScanDB).where(
                DevicePortScanDB.mac_address == mac_address
            ).order_by(DevicePortScanDB.scan_started_at.desc()).limit(1)
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
        
        out = PortScanResult(
            scan_id=scan_record.id,
            mac_address=str(scan_record.mac_address),
            ip_address=str(scan_record.ip_address),
            scan_status=scan_record.scan_status,
            scan_started_at=scan_record.scan_started_at,
            scan_completed_at=scan_record.scan_completed_at,
            error_message=scan_record.error_message,
            ports=ports
        )
        await set_json(cache_key, out.model_dump(mode="json"), ttl=60)
        return out


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


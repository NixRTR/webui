"""
Network device discovery collector
Discovers all devices on the network using ARP table and optional active scanning
"""
import subprocess
import re
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional
from ..models import DHCPLease
import os
from ..config import settings

logger = logging.getLogger(__name__)


class NetworkDevice:
    """Represents a discovered network device"""
    def __init__(
        self,
        network: str,
        ip_address: str,
        mac_address: str,
        hostname: Optional[str] = None,
        is_dhcp: bool = False,
        is_static: bool = False,
        is_online: bool = True,
        last_seen: datetime = None,
        vendor: Optional[str] = None
    ):
        self.network = network
        self.ip_address = ip_address
        self.mac_address = mac_address
        self.hostname = hostname or f"device-{ip_address.split('.')[-1]}"
        self.is_dhcp = is_dhcp
        self.is_static = is_static
        self.is_online = is_online
        self.last_seen = last_seen or datetime.now(timezone.utc)
        self.vendor = vendor


# Simple in-memory cache for ARP table (expensive subprocess call)
_arp_cache = None
_arp_cache_timestamp = None
_arp_cache_ttl = 10  # seconds (increased to reduce subprocess calls)

def parse_arp_table() -> Dict[str, Dict[str, str]]:
    """Parse system ARP table to find active devices
    
    Uses a short-lived cache to avoid expensive subprocess calls on every request.
    
    Returns:
        Dict[ip_address, {mac_address, interface}]
    """
    global _arp_cache, _arp_cache_timestamp
    
    # Check cache
    if _arp_cache is not None and _arp_cache_timestamp is not None:
        cache_age = (datetime.now(timezone.utc) - _arp_cache_timestamp).total_seconds()
        if cache_age < _arp_cache_ttl:
            return _arp_cache
    
    devices = {}
    
    try:
        # Try using 'ip neigh' (modern Linux). Resolve ip binary path.
        # Prefer explicit env var (NixOS module sets to /nix/store/... path)
        env_ip = os.environ.get("IP_BIN")
        ip_candidates = ([env_ip] if env_ip else []) + [
            '/run/current-system/sw/bin/ip',
            '/usr/sbin/ip',
            '/sbin/ip',
            'ip'
        ]
        ip_bin = None
        for c in ip_candidates:
            try:
                p = subprocess.run([c, '-V'], capture_output=True, text=True, timeout=2)
                if p.returncode == 0:
                    ip_bin = c
                    break
            except Exception:
                continue

        result = None
        if ip_bin:
            result = subprocess.run(
                [ip_bin, 'neigh', 'show'],
                capture_output=True,
                text=True,
                timeout=5
            )
        
        if result and result.returncode == 0:
            # Parse 'ip neigh' output
            # Format: 192.168.2.100 dev br0 lladdr aa:bb:cc:dd:ee:ff REACHABLE
            for line in result.stdout.splitlines():
                parts = line.split()
                if len(parts) >= 5 and 'lladdr' in parts:
                    ip = parts[0]
                    dev_idx = parts.index('dev') + 1 if 'dev' in parts else -1
                    mac_idx = parts.index('lladdr') + 1 if 'lladdr' in parts else -1
                    
                    if dev_idx > 0 and mac_idx > 0:
                        interface = parts[dev_idx]
                        mac = parts[mac_idx]
                        
                        # Only include bridge interfaces (br0, br1) and PPP
                        if interface.startswith('br') or interface.startswith('ppp'):
                            devices[ip] = {
                                'mac_address': mac.lower(),
                                'interface': interface
                            }
    except Exception as e:
        print(f"Error parsing ARP table: {e}")
        
    # Fallback: Try /proc/net/arp
    if not devices:
        try:
            arp_file = Path('/proc/net/arp')
            if arp_file.exists():
                with open(arp_file, 'r') as f:
                    lines = f.readlines()[1:]  # Skip header
                    for line in lines:
                        parts = line.split()
                        if len(parts) >= 6:
                            ip = parts[0]
                            mac = parts[3]
                            interface = parts[5]
                            
                            # Only include bridge interfaces
                            if interface.startswith('br') or interface.startswith('ppp'):
                                devices[ip] = {
                                    'mac_address': mac.lower(),
                                    'interface': interface
                                }
        except Exception as e:
            print(f"Error reading /proc/net/arp: {e}")
    
    # Update cache before returning
    _arp_cache = devices
    _arp_cache_timestamp = datetime.now(timezone.utc)
    
    return devices


def determine_network(ip_address: str, interface: str) -> str:
    """Determine which network a device belongs to based on IP and interface
    
    Args:
        ip_address: IP address of device
        interface: Network interface (br0, br1, etc.)
        
    Returns:
        'homelab' or 'lan'
    """
    # Based on IP range
    if ip_address.startswith('192.168.2.'):
        return 'homelab'
    elif ip_address.startswith('192.168.3.'):
        return 'lan'
    
    # Fallback to interface mapping
    if interface == 'br0':
        return 'homelab'
    elif interface == 'br1':
        return 'lan'
    
    # Default
    return 'homelab'


# Cache for vendor lookups (key: normalized MAC, value: vendor name or None)
_vendor_cache: Dict[str, Optional[str]] = {}
_netaddr_available = None

def _check_netaddr():
    """Check if netaddr library is available"""
    global _netaddr_available
    if _netaddr_available is None:
        try:
            from netaddr import EUI
            _netaddr_available = True
            logger.info("netaddr library available for MAC vendor lookup")
        except ImportError:
            _netaddr_available = False
            logger.warning("netaddr not available, using fallback for MAC vendor lookup")
    return _netaddr_available


def _normalize_mac(mac_address: str) -> str:
    """Normalize MAC address to lowercase with colons
    
    Handles various MAC address formats:
    - aa:bb:cc:dd:ee:ff (colons)
    - aa-bb-cc-dd-ee-ff (dashes)
    - aabbccddeeff (no separators)
    - AA:BB:CC:DD:EE:FF (uppercase)
    
    Args:
        mac_address: MAC address in any format
        
    Returns:
        Normalized MAC address in format aa:bb:cc:dd:ee:ff or original if invalid
    """
    if not mac_address:
        return mac_address
    
    # Remove common separators and convert to lowercase
    mac = mac_address.lower().replace('-', ':').replace('.', ':')
    
    # Try to parse as colon-separated format
    parts = [p for p in mac.split(':') if p]
    if len(parts) == 6:
        # Validate each part is 2 hex characters
        if all(len(p) == 2 and all(c in '0123456789abcdef' for c in p) for p in parts):
            return ':'.join(parts)
    
    # Try as continuous string (no separators)
    mac_clean = ''.join(c for c in mac if c.isalnum())
    if len(mac_clean) == 12 and all(c in '0123456789abcdef' for c in mac_clean):
        return ':'.join([mac_clean[i:i+2] for i in range(0, 12, 2)])
    
    # If we can't normalize, return lowercase version of original
    return mac_address.lower()


def lookup_mac_vendor(mac_address: str) -> Optional[str]:
    """Look up vendor from MAC address OUI with caching
    
    Uses the netaddr library which provides a comprehensive OUI database
    based on IEEE's manufacturer database. Falls back to a small hardcoded
    dictionary if the library is not available.
    
    Results are cached to avoid repeated lookups for the same MAC address.
    
    Args:
        mac_address: MAC address (format: aa:bb:cc:dd:ee:ff or any common format)
        
    Returns:
        Vendor name or None
    """
    if not mac_address or len(mac_address) < 8:
        return None
    
    # Normalize MAC address for consistent caching
    normalized_mac = _normalize_mac(mac_address)
    
    # Check cache first
    if normalized_mac in _vendor_cache:
        return _vendor_cache[normalized_mac]
    
    # Try using netaddr library for OUI lookup
    if _check_netaddr():
        try:
            from netaddr import EUI
            # Convert to format netaddr expects (accepts various formats)
            mac = EUI(normalized_mac)
            # Get the OUI (Organizationally Unique Identifier) registration
            oui = mac.oui
            if oui and oui.registration():
                vendor = oui.registration().org
                if vendor:
                    _vendor_cache[normalized_mac] = vendor
                    return vendor
        except Exception as e:
            logger.debug(f"netaddr OUI lookup failed for {normalized_mac}: {e}")
    
    # Fallback: Minimal hardcoded dictionary (keep for compatibility)
    oui = ':'.join(normalized_mac.split(':')[:3])
    fallback_vendors = {
        '00:07:a6': 'Leviton',
        'd8:a0:11': 'WiZ Connected',
        '48:a2:e6': 'Ubiquiti',
        'e8:9f:80': 'Ubiquiti',
        '10:d5:61': 'Espressif',
        '70:b8:f6': 'Universal Electronics',
        '6c:29:90': 'WiZ Connected',
        '84:7a:b6': 'Honeywell',
    }
    vendor = fallback_vendors.get(oui)
    _vendor_cache[normalized_mac] = vendor
    return vendor


def discover_network_devices(dhcp_leases: List[DHCPLease] = None) -> List[NetworkDevice]:
    """Discover all devices on the network
    
    Combines:
    - ARP table entries (active devices)
    - DHCP lease data (known DHCP clients)
    
    Deduplicates by MAC address - if the same MAC appears with multiple IPs,
    keeps the device with the most recent timestamp or prefers online devices.
    
    Args:
        dhcp_leases: Optional list of DHCP leases to merge
        
    Returns:
        List of NetworkDevice objects (one per MAC address)
    """
    # Use dictionary to deduplicate by MAC address
    # Key: MAC address (lowercase), Value: NetworkDevice
    devices_by_mac: Dict[str, NetworkDevice] = {}
    
    # Parse ARP table for active devices
    arp_devices = parse_arp_table()
    
    # Create DHCP lease lookup by MAC
    dhcp_by_mac = {}
    dhcp_by_ip = {}
    if dhcp_leases:
        for lease in dhcp_leases:
            dhcp_by_mac[lease.mac_address.lower()] = lease
            dhcp_by_ip[lease.ip_address] = lease
    
    # Process ARP table entries
    for ip, arp_data in arp_devices.items():
        mac = arp_data['mac_address']
        mac_lower = mac.lower()
        interface = arp_data['interface']
        network = determine_network(ip, interface)
        
        # Check if this device has a DHCP lease
        dhcp_lease = dhcp_by_mac.get(mac_lower) or dhcp_by_ip.get(ip)
        
        hostname = None
        is_dhcp = False
        is_static = False
        
        if dhcp_lease:
            hostname = dhcp_lease.hostname
            is_dhcp = True
            is_static = dhcp_lease.is_static
        
        # Look up vendor
        vendor = lookup_mac_vendor(mac)
        
        new_device = NetworkDevice(
            network=network,
            ip_address=ip,
            mac_address=mac,
            hostname=hostname,
            is_dhcp=is_dhcp,
            is_static=is_static,
            is_online=True,
            last_seen=datetime.now(timezone.utc),
            vendor=vendor
        )
        
        # Check if we already have this MAC address
        if mac_lower in devices_by_mac:
            existing_device = devices_by_mac[mac_lower]
            # Prefer the new device if:
            # 1. It's online and existing is offline, OR
            # 2. It has a more recent last_seen timestamp
            if (new_device.is_online and not existing_device.is_online) or \
               (new_device.last_seen > existing_device.last_seen):
                devices_by_mac[mac_lower] = new_device
        else:
            # First time seeing this MAC
            devices_by_mac[mac_lower] = new_device
    
    # Add DHCP leases that aren't in ARP table (offline devices)
    if dhcp_leases:
        for lease in dhcp_leases:
            mac_lower = lease.mac_address.lower()
            if mac_lower not in devices_by_mac:
                vendor = lookup_mac_vendor(lease.mac_address)
                
                device = NetworkDevice(
                    network=lease.network,
                    ip_address=lease.ip_address,
                    mac_address=lease.mac_address,
                    hostname=lease.hostname,
                    is_dhcp=True,
                    is_static=lease.is_static,
                    is_online=False,  # Not in ARP = offline
                    last_seen=lease.last_seen,
                    vendor=vendor
                )
                
                devices_by_mac[mac_lower] = device
    
    # Convert dictionary to list
    return list(devices_by_mac.values())


def get_device_count_by_network() -> Dict[str, Dict[str, int]]:
    """Get device counts by network
    
    Returns:
        Dict with counts: {
            'homelab': {'total': 10, 'online': 8, 'dhcp': 7},
            'lan': {'total': 5, 'online': 4, 'dhcp': 3}
        }
    """
    from .dhcp import parse_dnsmasq_leases
    
    dhcp_leases = parse_dnsmasq_leases()
    devices = discover_network_devices(dhcp_leases)
    
    counts = {
        'homelab': {'total': 0, 'online': 0, 'dhcp': 0},
        'lan': {'total': 0, 'online': 0, 'dhcp': 0}
    }
    
    for device in devices:
        if device.network in counts:
            counts[device.network]['total'] += 1
            if device.is_online:
                counts[device.network]['online'] += 1
            if device.is_dhcp:
                counts[device.network]['dhcp'] += 1
    
    return counts


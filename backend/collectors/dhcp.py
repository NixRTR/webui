"""
DHCP lease collector - parses dnsmasq DHCP lease files
"""
from datetime import datetime, timezone
from pathlib import Path
from typing import List
from ..models import DHCPLease
from ..config import settings


def parse_dnsmasq_leases() -> List[DHCPLease]:
    """Parse dnsmasq DHCP lease files (plain text format)
    
    Format: <expiry-time> <MAC> <IP> <hostname> <client-id>
    
    Returns:
        List[DHCPLease]: List of active DHCP leases (deduplicated by MAC per network)
    """
    # Get lease file paths from environment variable (space-separated)
    lease_files_str = getattr(settings, 'dnsmasq_lease_files', '')
    if not lease_files_str:
        return []
    
    lease_file_paths = lease_files_str.split()
    
    # Use dict with (network, MAC) as key to track unique devices per network
    # This automatically keeps the most recent entry for each device
    leases_dict = {}
    
    for lease_file_path in lease_file_paths:
        lease_file = Path(lease_file_path.strip())
        
        if not lease_file.exists():
            continue
        
        try:
            with open(lease_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    
                    # Parse dnsmasq format: <expiry-time> <MAC> <IP> <hostname> <client-id>
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    
                    try:
                        expiry_timestamp = int(parts[0])
                        mac = parts[1]
                        ip = parts[2]
                        hostname = parts[3] if len(parts) > 3 and parts[3] != '*' else ''
                        # client-id is optional (parts[4] if exists)
                    except (ValueError, IndexError):
                        continue
                    
                    # Skip invalid MAC addresses
                    if not mac or mac == '00:00:00:00:00:00':
                        continue
                    
                    # Determine network based on IP address
                    network = 'homelab' if ip.startswith('192.168.2.') else 'lan'
                    
                    # Parse timestamps
                    lease_end = None
                    lease_start = None
                    
                    try:
                        lease_end = datetime.fromtimestamp(expiry_timestamp, tz=timezone.utc)
                        # Estimate lease start (we don't have lease duration, so use current time as fallback)
                        # In practice, dnsmasq doesn't store lease start time, only expiry
                        lease_start = datetime.now(timezone.utc)
                    except (ValueError, OSError):
                        pass
                    
                    # Generate hostname if empty
                    if not hostname or hostname == '*':
                        hostname = f"client-{ip.split('.')[-1]}"
                    
                    dhcp_lease = DHCPLease(
                        network=network,
                        ip_address=ip,
                        mac_address=mac,
                        hostname=hostname,
                        lease_start=lease_start,
                        lease_end=lease_end,
                        last_seen=datetime.now(timezone.utc),
                        is_static=False
                    )
                    # Store in dict by (network, MAC) - tracks unique devices per network
                    # Automatically keeps the last (most recent) entry for each device
                    leases_dict[(network, mac)] = dhcp_lease
            
        except (IOError, OSError) as e:
            # Silently fail - lease file might be empty or being written
            pass
        except Exception as e:
            print(f"Error parsing dnsmasq leases from {lease_file}: {e}")
    
    return list(leases_dict.values())


async def trigger_new_device_scans(leases: List[DHCPLease]) -> None:
    """Trigger port scans for newly discovered devices from DHCP leases

    Args:
        leases: List of DHCP leases to check
    """
    import logging
    from ..workers.port_scanner import queue_new_device_scan

    logger = logging.getLogger(__name__)

    for lease in leases:
        try:
            queued = await queue_new_device_scan(lease.mac_address, lease.ip_address)
            if queued:
                logger.info(
                    f"Queued scan for DHCP device {lease.mac_address} ({lease.hostname})"
                )
        except Exception as e:
            logger.warning(
                f"Failed to queue scan for DHCP device {lease.mac_address}: {e}"
            )


def get_client_count_by_network() -> dict[str, int]:
    """Get count of DHCP clients by network
    
    Returns:
        dict: {'homelab': count, 'lan': count}
    """
    leases = parse_dnsmasq_leases()
    counts = {'homelab': 0, 'lan': 0}
    
    for lease in leases:
        if lease.network in counts:
            counts[lease.network] += 1
    
    return counts


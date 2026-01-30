"""
Parser for DHCP Nix configuration files (dnsmasq/dhcp-*.nix)
"""
import os
import logging
import re
from typing import Dict, List, Optional
from ..config import settings

logger = logging.getLogger(__name__)


def parse_dhcp_nix_file(network: str) -> Optional[Dict]:
    """Parse a DHCP Nix file for a specific network
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        Dictionary with DHCP configuration:
        - enable: bool
        - start: str (IP address)
        - end: str (IP address)
        - leaseTime: str
        - dnsServers: list of IP addresses
        - dynamicDomain: str (optional, may be empty)
        - reservations: list of {hostname, hwAddress, ipAddress, comment}
    """
    # Determine file path
    if network == "homelab":
        file_path = settings.dhcp_homelab_file
    elif network == "lan":
        file_path = settings.dhcp_lan_file
    else:
        logger.error(f"Invalid network: {network}")
        return None
    
    if not os.path.exists(file_path):
        logger.warning(f"DHCP Nix file not found at {file_path}")
        return None
    
    logger.debug(f"Parsing DHCP Nix file: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        config = {
            'enable': True,  # Default
            'start': '',
            'end': '',
            'leaseTime': '1h',
            'dnsServers': [],
            'dynamicDomain': '',
            'reservations': []
        }
        
        # Extract enable
        enable_match = re.search(r'enable\s*=\s*(true|false)', content)
        if enable_match:
            config['enable'] = enable_match.group(1) == 'true'
        
        # Extract start
        start_match = re.search(r'start\s*=\s*"([^"]+)"', content)
        if start_match:
            config['start'] = start_match.group(1)
        
        # Extract end
        end_match = re.search(r'end\s*=\s*"([^"]+)"', content)
        if end_match:
            config['end'] = end_match.group(1)
        
        # Extract leaseTime
        lease_match = re.search(r'leaseTime\s*=\s*"([^"]+)"', content)
        if lease_match:
            config['leaseTime'] = lease_match.group(1)
        
        # Extract dnsServers (array)
        dns_match = re.search(r'dnsServers\s*=\s*\[([^\]]+)\]', content, re.DOTALL)
        if dns_match:
            dns_servers_str = dns_match.group(1)
            # Extract IP addresses from the array
            ip_pattern = r'"([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)"'
            config['dnsServers'] = re.findall(ip_pattern, dns_servers_str)
        
        # Extract dynamicDomain (may be empty string)
        domain_match = re.search(r'dynamicDomain\s*=\s*"([^"]*)"', content)
        if domain_match:
            config['dynamicDomain'] = domain_match.group(1)
        
        # Extract reservations: either inline list or import
        reservations_import_match = re.search(r'reservations\s*=\s*import\s+', content)
        if reservations_import_match:
            # Reservations are in a separate file; main file has no inline list
            config['reservations'] = []
        else:
            reservations_match = re.search(r'reservations\s*=\s*\[(.*?)\]', content, re.DOTALL)
            if reservations_match:
                reservations_block = reservations_match.group(1)
                config['reservations'] = _parse_dhcp_reservations(reservations_block)
        
        logger.debug(f"Parsed DHCP config for {network}: {len(config['reservations'])} reservations")
        return config
        
    except Exception as e:
        logger.error(f"Error parsing DHCP Nix file {file_path}: {type(e).__name__}: {str(e)}", exc_info=True)
        return None


def _parse_dhcp_reservations(content: str) -> List[Dict[str, str]]:
    """Parse DHCP reservations from Nix content
    
    Args:
        content: Content between reservations = [ ... ]
        
    Returns:
        List of reservation dictionaries with hostname, hwAddress, ipAddress, comment
    """
    reservations = []
    
    # Pattern to match: { hostname = "name"; hwAddress = "mac"; ipAddress = "ip"; comment = "comment"; }
    # Also handles missing comment field
    pattern = r'\{\s*hostname\s*=\s*"([^"]+)";\s*hwAddress\s*=\s*"([^"]+)";\s*ipAddress\s*=\s*"([^"]+)";(?:\s*comment\s*=\s*"([^"]*)";)?\s*\}'
    
    for match in re.finditer(pattern, content, re.DOTALL):
        hostname = match.group(1)
        hw_address = match.group(2)
        ip_address = match.group(3)
        comment = match.group(4) if match.group(4) else ""
        
        # Skip commented-out lines
        line_start = content.rfind('\n', 0, match.start()) + 1
        line_prefix = content[line_start:match.start()].strip()
        if line_prefix.startswith('#'):
            continue
        
        reservations.append({
            'hostname': hostname,
            'hwAddress': hw_address,
            'ipAddress': ip_address,
            'comment': comment
        })
    
    return reservations


def get_dhcp_reservations_file_path(network: str) -> Optional[str]:
    """Return the path to the reservations-only Nix file for a network, or None if invalid."""
    if network == "homelab":
        return settings.dhcp_reservations_homelab_file
    if network == "lan":
        return settings.dhcp_reservations_lan_file
    return None


def parse_dhcp_reservations_nix_file(network: str) -> List[Dict[str, str]]:
    """Parse the reservations-only Nix file for a network (dhcp-reservations-<network>.nix).
    
    Returns a list of reservation dicts with keys hostname, hwAddress, ipAddress, comment.
    Returns [] if the file does not exist or cannot be parsed (backward compatibility).
    """
    file_path = get_dhcp_reservations_file_path(network)
    if not file_path or not os.path.exists(file_path):
        logger.debug(f"DHCP reservations file not found for {network}: {file_path}")
        return []
    
    logger.debug(f"Parsing DHCP reservations file: {file_path}")
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # File is a Nix list: [ { hostname = "x"; hwAddress = "mac"; ... } ... ]
        list_match = re.search(r'\[(.*)\]', content, re.DOTALL)
        if not list_match:
            return []
        reservations_block = list_match.group(1)
        return _parse_dhcp_reservations(reservations_block)
    except Exception as e:
        logger.warning(f"Error parsing DHCP reservations file {file_path}: {e}")
        return []

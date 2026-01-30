"""
Generate dnsmasq DHCP configuration from config files (source of truth)
Merges router-config.nix with WebUI-managed config files
"""
import logging
import os
import re
from typing import Optional
from ..config import settings
from .config_reader import (
    get_dhcp_networks_from_config,
    get_dhcp_reservations_from_config
)

logger = logging.getLogger(__name__)

# Network to bridge interface mapping
NETWORK_BRIDGE_MAP = {
    'homelab': 'br0',
    'lan': 'br1',
}


def _get_router_ip_from_config(network: str) -> Optional[str]:
    """Get router IP address for a network from router-config.nix
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        Router IP address or None if not found
    """
    config_path = settings.router_config_file
    
    if not os.path.exists(config_path):
        logger.warning(f"router-config.nix not found at {config_path}")
        return None
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Pattern to match: network = { ... ipAddress = "192.168.x.1"; ... }
        pattern = rf'{network}\s*=\s*\{{[^}}]*ipAddress\s*=\s*"([^"]+)"'
        match = re.search(pattern, content, re.DOTALL)
        
        if match:
            return match.group(1)
        
        logger.debug(f"Could not find ipAddress for network {network} in router-config.nix")
        return None
    except Exception as e:
        logger.error(f"Error reading router-config.nix: {e}")
        return None


def generate_dnsmasq_dhcp_config(network: str) -> Optional[str]:
    """Generate dnsmasq DHCP configuration from config files (source of truth)
    
    Reads from router-config.nix and webui-dhcp.conf, merging them.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        dnsmasq DHCP configuration as string, or None if DHCP is disabled for this network
    """
    if network not in ['homelab', 'lan']:
        raise ValueError(f"Invalid network: {network}. Must be 'homelab' or 'lan'")
    
    # Get DHCP network configuration from config files
    networks = get_dhcp_networks_from_config()
    dhcp_network = next((n for n in networks if n['network'] == network), None)
    
    if not dhcp_network or not dhcp_network.get('enabled', True):
        logger.debug(f"DHCP disabled or not configured for network {network}")
        return None
    
    lines = []
    lines.append("# WebUI-managed DHCP configuration")
    lines.append("# Generated automatically - do not edit manually")
    lines.append("")
    
    bridge = NETWORK_BRIDGE_MAP.get(network, f"br{network}")
    router_ip = _get_router_ip_from_config(network)
    if not router_ip:
        # Fallback to defaults if config not available
        router_ip = '192.168.2.1' if network == 'homelab' else '192.168.3.1'
        logger.warning(f"Could not read router IP from config, using fallback: {router_ip}")
    
    # DHCP range
    lines.append(f"dhcp-range={bridge},{dhcp_network['start']},{dhcp_network['end']},{dhcp_network['lease_time']}")
    
    # DHCP option 3: Router (gateway)
    lines.append(f"dhcp-option={bridge},3,{router_ip}")
    
    # DHCP option 6: DNS servers
    dns_servers = dhcp_network.get('dns_servers') or [router_ip]
    dns_servers_str = ",".join(str(ip) for ip in dns_servers)
    lines.append(f"dhcp-option={bridge},6,{dns_servers_str}")
    
    # DHCP option 15: Domain name (if dynamic domain is set)
    if dhcp_network.get('dynamic_domain'):
        lines.append(f"dhcp-option={bridge},15,{dhcp_network['dynamic_domain']}")
    
    # DHCP authoritative
    lines.append("dhcp-authoritative")
    
    # Static reservations (dhcp-host=MAC,hostname,IP)
    # Use hostname.dynamic_domain when dynamic_domain is set so the name matches dynamic-dns.conf
    # and dnsmasq does not report "DHCP host has multiple names"
    reservations = get_dhcp_reservations_from_config(network)
    dynamic_domain = (dhcp_network.get('dynamic_domain') or '').strip()
    
    for reservation in reservations:
        if not reservation.get('enabled', True):
            continue
        hostname = reservation['hostname']
        if dynamic_domain:
            hostname = f"{hostname}.{dynamic_domain}"
        comment = f"  # {reservation['comment']}" if reservation.get('comment') else ""
        lines.append(f"dhcp-host={reservation['hw_address']},{hostname},{reservation['ip_address']}{comment}")
    
    return "\n".join(lines)

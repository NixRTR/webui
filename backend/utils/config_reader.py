"""
Read DNS and DHCP configuration from config files (source of truth)
Merges router-config.nix with WebUI-managed config files
"""
import os
import logging
from typing import Dict, List, Optional
from ..config import settings
from .dns import parse_nix_config, extract_base_domain
from .dhcp import parse_router_config_dhcp
from .dnsmasq_parser import parse_dnsmasq_config_file

logger = logging.getLogger(__name__)


def get_dns_zones_from_config(network: str) -> List[Dict]:
    """Get DNS zones from config files (router-config.nix + webui-dns.conf)
    
    Merges zones from both sources, with WebUI config taking precedence.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        List of zone dictionaries
    """
    zones = set()
    zone_data = {}  # zone_name -> zone dict
    
    # Read from router-config.nix
    config = parse_nix_config()
    if config:
        network_config = config.get(network, {})
        a_records = network_config.get('a_records', {})
        cname_records = network_config.get('cname_records', {})
        
        # Extract unique base domains (zones)
        for hostname in list(a_records.keys()) + list(cname_records.keys()):
            base_domain = extract_base_domain(hostname)
            zones.add(base_domain)
            if base_domain not in zone_data:
                zone_data[base_domain] = {
                    'name': base_domain,
                    'network': network,
                    'authoritative': True,
                    'enabled': True
                }
    
    # Read from WebUI-managed dnsmasq config (overrides/additions)
    webui_config_path = f"/var/lib/dnsmasq/{network}/webui-dns.conf"
    if os.path.exists(webui_config_path):
        parsed = parse_dnsmasq_config_file(webui_config_path)
        
        # Add zones from authoritative domains
        for domain in parsed['authoritative']:
            zones.add(domain)
            if domain not in zone_data:
                zone_data[domain] = {
                    'name': domain,
                    'network': network,
                    'authoritative': True,
                    'enabled': True
                }
        
        # Add zones from wildcards
        for wildcard in parsed['wildcards']:
            domain = wildcard['domain']
            zones.add(domain)
            if domain not in zone_data:
                zone_data[domain] = {
                    'name': domain,
                    'network': network,
                    'authoritative': True,  # Wildcards imply authoritative
                    'enabled': True
                }
        
        # Add zones from host records
        for record in parsed['host_records']:
            hostname = record['hostname']
            parts = hostname.split('.')
            if len(parts) >= 2:
                base_domain = '.'.join(parts[-2:])
                zones.add(base_domain)
                if base_domain not in zone_data:
                    zone_data[base_domain] = {
                        'name': base_domain,
                        'network': network,
                        'authoritative': True,
                        'enabled': True
                    }
    
    # Return sorted list
    return [zone_data[zone] for zone in sorted(zones)]


def get_dns_records_from_config(network: str, zone_name: Optional[str] = None) -> List[Dict]:
    """Get DNS records from config files (router-config.nix + webui-dns.conf)
    
    Merges records from both sources, with WebUI config taking precedence.
    
    Args:
        network: Network name ("homelab" or "lan")
        zone_name: Optional zone name to filter by
        
    Returns:
        List of record dictionaries with zone_name included
    """
    records = {}  # name -> record dict (to handle overrides)
    
    # Read from router-config.nix
    config = parse_nix_config()
    if config:
        network_config = config.get(network, {})
        a_records = network_config.get('a_records', {})
        cname_records = network_config.get('cname_records', {})
        
        # Process A records
        for hostname, record_data in a_records.items():
            base_domain = extract_base_domain(hostname)
            if zone_name and base_domain != zone_name:
                continue
            
            records[hostname] = {
                'name': hostname,
                'type': 'A',
                'value': record_data['ip'],
                'comment': record_data.get('comment', ''),
                'zone_name': base_domain,
                'network': network,
                'enabled': True
            }
        
        # Process CNAME records
        for hostname, record_data in cname_records.items():
            base_domain = extract_base_domain(hostname)
            if zone_name and base_domain != zone_name:
                continue
            
            records[hostname] = {
                'name': hostname,
                'type': 'CNAME',
                'value': record_data['target'],
                'comment': record_data.get('comment', ''),
                'zone_name': base_domain,
                'network': network,
                'enabled': True
            }
    
    # Read from WebUI-managed dnsmasq config (overrides/additions)
    webui_config_path = f"/var/lib/dnsmasq/{network}/webui-dns.conf"
    if os.path.exists(webui_config_path):
        parsed = parse_dnsmasq_config_file(webui_config_path)
        
        # Process wildcards (convert to CNAME *.domain -> domain)
        for wildcard in parsed['wildcards']:
            domain = wildcard['domain']
            if zone_name and domain != zone_name:
                continue
            
            wildcard_name = f"*.{domain}"
            records[wildcard_name] = {
                'name': wildcard_name,
                'type': 'CNAME',
                'value': domain,  # CNAME target
                'comment': wildcard.get('comment', ''),
                'zone_name': domain,
                'network': network,
                'enabled': True
            }
        
        # Process host records (A records)
        for record in parsed['host_records']:
            hostname = record['hostname']
            parts = hostname.split('.')
            if len(parts) >= 2:
                base_domain = '.'.join(parts[-2:])
                if zone_name and base_domain != zone_name:
                    continue
                
                # Override or add record from WebUI config
                records[hostname] = {
                    'name': hostname,
                    'type': 'A',
                    'value': record['ip'],
                    'comment': record.get('comment', ''),
                    'zone_name': base_domain,
                    'network': network,
                    'enabled': True
                }
    
    return list(records.values())


def get_dhcp_networks_from_config() -> List[Dict]:
    """Get DHCP networks from router-config.nix
    
    Returns:
        List of DHCP network dictionaries
    """
    config = parse_router_config_dhcp()
    if not config:
        return []
    
    networks = []
    for network_name in ['homelab', 'lan']:
        network_config = config.get(network_name, {})
        if not network_config:
            continue
        
        networks.append({
            'network': network_name,
            'enabled': network_config.get('enable', True),
            'start': network_config.get('start', ''),
            'end': network_config.get('end', ''),
            'lease_time': network_config.get('leaseTime', '1h'),
            'dns_servers': network_config.get('dnsServers', []),
            'dynamic_domain': network_config.get('dynamicDomain', '')
        })
    
    return networks


def get_dhcp_reservations_from_config(network: str) -> List[Dict]:
    """Get DHCP reservations from router-config.nix
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        List of reservation dictionaries
    """
    config = parse_router_config_dhcp()
    if not config:
        return []
    
    network_config = config.get(network, {})
    reservations = network_config.get('reservations', [])
    
    result = []
    for res in reservations:
        result.append({
            'hostname': res['hostname'],
            'hw_address': res['hwAddress'],
            'ip_address': res['ipAddress'],
            'comment': res.get('comment', ''),
            'network': network,
            'enabled': True
        })
    
    return result

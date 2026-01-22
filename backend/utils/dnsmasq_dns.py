"""
Generate dnsmasq DNS configuration from config files (source of truth)
Merges router-config.nix with WebUI-managed config files
"""
import logging
from typing import Dict, List, Optional
from ..utils.config_reader import get_dns_zones_from_config, get_dns_records_from_config

logger = logging.getLogger(__name__)


def generate_dnsmasq_dns_config(network: str) -> str:
    """Generate dnsmasq DNS configuration from config files
    
    Reads from router-config.nix and webui-dns.conf, merging them.
    WebUI-managed configs override router-config.nix.
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        dnsmasq configuration as string
    """
    if network not in ['homelab', 'lan']:
        raise ValueError(f"Invalid network: {network}. Must be 'homelab' or 'lan'")
    
    lines = []
    lines.append("# WebUI-managed DNS configuration")
    lines.append("# Generated automatically - do not edit manually")
    lines.append("")
    
    # Get zones and records from config files
    zones = get_dns_zones_from_config(network)
    records = get_dns_records_from_config(network)
    
    if not zones and not records:
        logger.debug(f"No DNS configuration found for network {network}")
        return "\n".join(lines)
    
    # Collect wildcards and host records
    wildcards = []  # List of {domain, ip, comment}
    host_records = []  # List of {hostname, ip, comment}
    authoritative_domains = set()  # Domains that should have local= directive
    
    # Process zones
    for zone in zones:
        if zone.get('authoritative'):
            authoritative_domains.add(zone['name'])
    
    # Process records
    for record in records:
        if record['type'] == 'A':
            # Check if this is a wildcard
            if record['name'].startswith('*.'):
                # Extract domain (remove *. prefix)
                domain = record['name'][2:]  # Remove "*."
                wildcards.append({
                    'domain': domain,
                    'ip': record['value'],
                    'comment': record.get('comment', '')
                })
            else:
                # Regular A record
                host_records.append({
                    'hostname': record['name'],
                    'ip': record['value'],
                    'comment': record.get('comment', '')
                })
        elif record['type'] == 'CNAME':
            # For CNAME, we need to resolve the target to an IP
            target = record['value']
            
            # First check if target is a wildcard
            if record['name'].startswith('*.'):
                domain = record['name'][2:]  # Remove "*."
                # Try to find the target's IP
                target_ip = _resolve_cname_target_from_records(records, target)
                if target_ip:
                    wildcards.append({
                        'domain': domain,
                        'ip': target_ip,
                        'comment': record.get('comment', '')
                    })
            else:
                # Regular CNAME - resolve to IP
                target_ip = _resolve_cname_target_from_records(records, target)
                if target_ip:
                    host_records.append({
                        'hostname': record['name'],
                        'ip': target_ip,
                        'comment': record.get('comment', '')
                    })
    
    # Remove base domains from authoritative if they have wildcards
    # (address= already handles wildcards and local resolution)
    wildcard_domains = {w['domain'] for w in wildcards}
    authoritative_domains = authoritative_domains - wildcard_domains
    
    # Generate config lines
    
    # Authoritative zones (local= directive)
    # Only add if no wildcards exist for that domain
    for domain in sorted(authoritative_domains):
        lines.append(f"local=/{domain}/")
    
    # Wildcard domains (address=/domain/IP)
    for wildcard in sorted(wildcards, key=lambda x: x['domain']):
        comment = f"  # {wildcard['comment']}" if wildcard['comment'] else ""
        lines.append(f"address=/{wildcard['domain']}/{wildcard['ip']}{comment}")
    
    # Host records (host-record=hostname,IP)
    for record in sorted(host_records, key=lambda x: x['hostname']):
        comment = f"  # {record['comment']}" if record['comment'] else ""
        lines.append(f"host-record={record['hostname']},{record['ip']}{comment}")
    
    return "\n".join(lines)


def _resolve_cname_target_from_records(records: List[Dict], target: str) -> Optional[str]:
    """Resolve a CNAME target to an IP address from records list
    
    Args:
        records: List of record dictionaries
        target: Target hostname from CNAME record
        
    Returns:
        IP address if found, None otherwise
    """
    # First, try to find an A record with this exact name
    for record in records:
        if record['name'] == target and record['type'] == 'A':
            return record['value']
    
    # If not found, try to extract base domain and check for wildcard
    parts = target.split('.')
    if len(parts) >= 2:
        base_domain = '.'.join(parts[-2:])
        # Check for wildcard record
        wildcard_name = f"*.{base_domain}"
        for record in records:
            if record['name'] == wildcard_name and record['type'] == 'A':
                return record['value']
    
    logger.debug(f"Could not resolve CNAME target {target} to IP")
    return None



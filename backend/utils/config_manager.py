"""
Manage DNS/DHCP configuration by reading from and writing to config files
Handles merging router-config.nix with WebUI-managed configs
"""
import logging
from typing import Dict, List, Optional
from .config_reader import (
    get_dns_zones_from_config,
    get_dns_records_from_config,
    get_dhcp_networks_from_config,
    get_dhcp_reservations_from_config
)
from .dnsmasq_dns import generate_dnsmasq_dns_config
from .dnsmasq_dhcp import generate_dnsmasq_dhcp_config
from .config_writer import write_dns_config, write_dhcp_config

logger = logging.getLogger(__name__)


def update_dns_record_in_config(
    network: str,
    operation: str,  # "add", "update", "delete"
    record_name: str,
    record_type: str,
    record_value: Optional[str] = None,
    record_comment: Optional[str] = None,
    zone_name: Optional[str] = None
) -> None:
    """Update DNS record in WebUI config file
    
    Reads current config, applies change, and writes back.
    
    Args:
        network: Network name
        operation: Operation type
        record_name: Record name (hostname or wildcard)
        record_type: Record type ("A" or "CNAME")
        record_value: Record value (IP for A, target for CNAME)
        record_comment: Optional comment
        zone_name: Zone name (if not provided, extracted from record_name)
    """
    # Get current config from files
    all_records = get_dns_records_from_config(network)
    
    # Determine zone if not provided
    if not zone_name:
        parts = record_name.split('.')
        if len(parts) >= 2:
            zone_name = '.'.join(parts[-2:])
        else:
            raise ValueError(f"Cannot determine zone from record name: {record_name}")
    
    # Filter to current zone
    zone_records = [r for r in all_records if r['zone_name'] == zone_name]
    other_records = [r for r in all_records if r['zone_name'] != zone_name]
    
    # Apply operation
    if operation == "add":
        # Check if record already exists
        existing = next((r for r in zone_records if r['name'] == record_name), None)
        if existing:
            raise ValueError(f"Record {record_name} already exists")
        zone_records.append({
            'name': record_name,
            'type': record_type,
            'value': record_value,
            'comment': record_comment or '',
            'zone_name': zone_name,
            'network': network,
            'enabled': True
        })
    elif operation == "update":
        # Find and update record
        idx = next((i for i, r in enumerate(zone_records) if r['name'] == record_name), None)
        if idx is None:
            raise ValueError(f"Record {record_name} not found")
        zone_records[idx].update({
            'type': record_type,
            'value': record_value,
            'comment': record_comment or ''
        })
    elif operation == "delete":
        # Remove record
        zone_records = [r for r in zone_records if r['name'] != record_name]
    
    # Merge back with other zones
    updated_all_records = other_records + zone_records
    
    # Generate config from all records
    # We need to rebuild the config structure that generate_dnsmasq_dns_config expects
    # For now, let's directly generate the dnsmasq config format
    
    # Group by zone and generate config
    lines = []
    lines.append("# WebUI-managed DNS configuration")
    lines.append("# Generated automatically - do not edit manually")
    lines.append("")
    
    # Group records by zone
    records_by_zone = {}
    for record in updated_all_records:
        zone = record['zone_name']
        if zone not in records_by_zone:
            records_by_zone[zone] = []
        records_by_zone[zone].append(record)
    
    # Get zones to check authoritative
    zones = get_dns_zones_from_config(network)
    authoritative_domains = {z['name'] for z in zones if z.get('authoritative')}
    
    # Generate config for each zone
    wildcards = []
    host_records = []
    
    for zone_name, zone_recs in records_by_zone.items():
        for record in zone_recs:
            if record['type'] == 'A':
                if record['name'].startswith('*.'):
                    domain = record['name'][2:]
                    wildcards.append({
                        'domain': domain,
                        'ip': record['value'],
                        'comment': record.get('comment', '')
                    })
                else:
                    host_records.append({
                        'hostname': record['name'],
                        'ip': record['value'],
                        'comment': record.get('comment', '')
                    })
            elif record['type'] == 'CNAME':
                # Resolve CNAME to IP
                target = record['value']
                target_ip = _resolve_cname_from_records(updated_all_records, target)
                if target_ip:
                    if record['name'].startswith('*.'):
                        domain = record['name'][2:]
                        wildcards.append({
                            'domain': domain,
                            'ip': target_ip,
                            'comment': record.get('comment', '')
                        })
                    else:
                        host_records.append({
                            'hostname': record['name'],
                            'ip': target_ip,
                            'comment': record.get('comment', '')
                        })
    
    # Remove base domains from authoritative if they have wildcards
    wildcard_domains = {w['domain'] for w in wildcards}
    authoritative_domains = authoritative_domains - wildcard_domains
    
    # Generate config lines
    for domain in sorted(authoritative_domains):
        lines.append(f"local=/{domain}/")
    
    for wildcard in sorted(wildcards, key=lambda x: x['domain']):
        comment = f"  # {wildcard['comment']}" if wildcard['comment'] else ""
        lines.append(f"address=/{wildcard['domain']}/{wildcard['ip']}{comment}")
    
    for record in sorted(host_records, key=lambda x: x['hostname']):
        comment = f"  # {record['comment']}" if record['comment'] else ""
        lines.append(f"host-record={record['hostname']},{record['ip']}{comment}")
    
    config_content = "\n".join(lines)
    
    # Write to config file
    write_dns_config(network, config_content)


def update_dhcp_reservation_in_config(
    network: str,
    operation: str,  # "add", "update", "delete"
    hw_address: str,
    hostname: Optional[str] = None,
    ip_address: Optional[str] = None,
    comment: Optional[str] = None
) -> None:
    """Update DHCP reservation in WebUI config file
    
    Args:
        network: Network name
        operation: Operation type
        hw_address: MAC address (identifier)
        hostname: Hostname (for add/update)
        ip_address: IP address (for add/update)
        comment: Optional comment
    """
    # Get current config from files
    reservations = get_dhcp_reservations_from_config(network)
    
    # Apply operation
    if operation == "add":
        if any(r['hw_address'] == hw_address for r in reservations):
            raise ValueError(f"Reservation with MAC {hw_address} already exists")
        reservations.append({
            'hostname': hostname,
            'hw_address': hw_address,
            'ip_address': ip_address,
            'comment': comment or '',
            'network': network,
            'enabled': True
        })
    elif operation == "update":
        idx = next((i for i, r in enumerate(reservations) if r['hw_address'] == hw_address), None)
        if idx is None:
            raise ValueError(f"Reservation with MAC {hw_address} not found")
        reservations[idx].update({
            'hostname': hostname,
            'ip_address': ip_address,
            'comment': comment or ''
        })
    elif operation == "delete":
        reservations = [r for r in reservations if r['hw_address'] != hw_address]
    
    # Generate config content
    lines = []
    lines.append("# WebUI-managed DHCP configuration")
    lines.append("# Generated automatically - do not edit manually")
    lines.append("")
    
    for res in reservations:
        comment_str = f"  # {res['comment']}" if res.get('comment') else ""
        lines.append(f"dhcp-host={res['hw_address']},{res['hostname']},{res['ip_address']}{comment_str}")
    
    config_content = "\n".join(lines)
    
    # Write to config file
    write_dhcp_config(network, config_content)


def _resolve_cname_from_records(records: List[Dict], target: str) -> Optional[str]:
    """Resolve CNAME target to IP from records list"""
    # Try exact match
    for record in records:
        if record['name'] == target and record['type'] == 'A':
            return record['value']
    
    # Try wildcard
    parts = target.split('.')
    if len(parts) >= 2:
        base_domain = '.'.join(parts[-2:])
        wildcard_name = f"*.{base_domain}"
        for record in records:
            if record['name'] == wildcard_name and record['type'] == 'A':
                return record['value']
    
    return None

"""
Write DNS/DHCP configuration to webui-*.conf files
These files override router-config.nix settings
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


async def update_dns_config_file(
    session,
    network: str,
    operation: str,  # "add", "update", "delete"
    record_data: Dict,
    zone_name: str
) -> None:
    """Update DNS config file by merging current config with changes
    
    Args:
        session: Database session (for history tracking)
        network: Network name
        operation: Operation type
        record_data: Record data (for add/update) or record identifier (for delete)
        zone_name: Zone name
    """
    # Get current config from files
    all_records = get_dns_records_from_config(network)
    
    # Filter to current zone
    zone_records = [r for r in all_records if r['zone_name'] == zone_name]
    
    # Apply operation
    if operation == "add":
        # Check if record already exists
        existing = next((r for r in zone_records if r['name'] == record_data['name']), None)
        if existing:
            raise ValueError(f"Record {record_data['name']} already exists")
        zone_records.append(record_data)
    elif operation == "update":
        # Find and update record
        idx = next((i for i, r in enumerate(zone_records) if r['name'] == record_data['name']), None)
        if idx is None:
            raise ValueError(f"Record {record_data['name']} not found")
        zone_records[idx] = record_data
    elif operation == "delete":
        # Remove record
        zone_records = [r for r in zone_records if r['name'] != record_data['name']]
    
    # Generate new config from updated records
    # We need to generate config for all zones, not just this one
    all_zones = get_dns_zones_from_config(network)
    all_network_records = get_dns_records_from_config(network)
    
    # Replace records for this zone with updated ones
    other_zone_records = [r for r in all_network_records if r['zone_name'] != zone_name]
    updated_all_records = other_zone_records + zone_records
    
    # Generate dnsmasq config from the merged records
    # We'll need to create a temporary structure that generate_dnsmasq_dns_config can use
    # For now, let's write directly to the config file format
    
    # Build config content
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
    
    # Generate config for each zone
    for zone_name, zone_recs in records_by_zone.items():
        # Check for wildcards
        wildcards = [r for r in zone_recs if r['name'].startswith('*.')]
        host_records = [r for r in zone_recs if not r['name'].startswith('*.')]
        
        # Add wildcards as address= directives
        for wildcard in wildcards:
            domain = wildcard['name'][2:]  # Remove "*."
            if wildcard['type'] == 'CNAME':
                # Resolve CNAME target to IP
                target = wildcard['value']
                target_record = next((r for r in updated_all_records if r['name'] == target and r['type'] == 'A'), None)
                if target_record:
                    ip = target_record['value']
                    comment = f"  # {wildcard['comment']}" if wildcard.get('comment') else ""
                    lines.append(f"address=/{domain}/{ip}{comment}")
            elif wildcard['type'] == 'A':
                comment = f"  # {wildcard['comment']}" if wildcard.get('comment') else ""
                lines.append(f"address=/{domain}/{wildcard['value']}{comment}")
        
        # Add host records
        for record in host_records:
            if record['type'] == 'A':
                comment = f"  # {record['comment']}" if record.get('comment') else ""
                lines.append(f"host-record={record['name']},{record['value']}{comment}")
            elif record['type'] == 'CNAME':
                # Resolve CNAME to IP
                target = record['value']
                target_record = next((r for r in updated_all_records if r['name'] == target and r['type'] == 'A'), None)
                if target_record:
                    comment = f"  # {record['comment']}" if record.get('comment') else ""
                    lines.append(f"host-record={record['name']},{target_record['value']}{comment}")
    
    config_content = "\n".join(lines)
    
    # Write to config file
    write_dns_config(network, config_content)


async def update_dhcp_config_file(
    session,
    network: str,
    operation: str,  # "add", "update", "delete"
    reservation_data: Optional[Dict] = None
) -> None:
    """Update DHCP config file by merging current config with changes
    
    Args:
        session: Database session (for history tracking)
        network: Network name
        operation: Operation type
        reservation_data: Reservation data (for add/update) or identifier (for delete)
    """
    # Get current config from files
    reservations = get_dhcp_reservations_from_config(network)
    
    # Apply operation
    if operation == "add":
        if any(r['hw_address'] == reservation_data['hw_address'] for r in reservations):
            raise ValueError(f"Reservation with MAC {reservation_data['hw_address']} already exists")
        reservations.append(reservation_data)
    elif operation == "update":
        idx = next((i for i, r in enumerate(reservations) if r['hw_address'] == reservation_data['hw_address']), None)
        if idx is None:
            raise ValueError(f"Reservation with MAC {reservation_data['hw_address']} not found")
        reservations[idx] = reservation_data
    elif operation == "delete":
        reservations = [r for r in reservations if r['hw_address'] != reservation_data['hw_address']]
    
    # Generate config content
    lines = []
    lines.append("# WebUI-managed DHCP configuration")
    lines.append("# Generated automatically - do not edit manually")
    lines.append("")
    
    for res in reservations:
        comment = f"  # {res['comment']}" if res.get('comment') else ""
        lines.append(f"dhcp-host={res['hw_address']},{res['hostname']},{res['ip_address']}{comment}")
    
    config_content = "\n".join(lines)
    
    # Write to config file
    write_dhcp_config(network, config_content)

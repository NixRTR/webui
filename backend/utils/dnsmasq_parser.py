"""
Parse dnsmasq configuration files and extract DNS/DHCP records
"""
import os
import re
import logging
from typing import Dict, List, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import DnsZoneDB, DnsRecordDB
from ..config import settings

logger = logging.getLogger(__name__)


def parse_dnsmasq_config_file(config_path: str) -> Dict[str, List[Dict]]:
    """Parse a dnsmasq config file and extract DNS records
    
    Args:
        config_path: Path to dnsmasq config file
        
    Returns:
        Dictionary with:
        - 'authoritative': List of domains with local= directive
        - 'wildcards': List of {domain, ip, comment}
        - 'host_records': List of {hostname, ip, comment}
    """
    result = {
        'authoritative': [],
        'wildcards': [],
        'host_records': []
    }
    
    if not os.path.exists(config_path):
        logger.debug(f"Config file not found: {config_path}")
        return result
    
    try:
        with open(config_path, 'r') as f:
            content = f.read()
        
        # Parse local= directives (authoritative zones)
        # Format: local=/domain/
        local_pattern = r'local=/([^/]+)/'
        for match in re.finditer(local_pattern, content):
            domain = match.group(1)
            result['authoritative'].append(domain)
        
        # Parse address= directives (wildcards)
        # Format: address=/domain/IP  # comment
        address_pattern = r'address=/([^/]+)/([^\s#]+)(?:\s*#\s*(.+))?'
        for match in re.finditer(address_pattern, content):
            domain = match.group(1)
            ip = match.group(2).strip()
            comment = match.group(3).strip() if match.group(3) else ""
            result['wildcards'].append({
                'domain': domain,
                'ip': ip,
                'comment': comment
            })
        
        # Parse host-record= directives
        # Format: host-record=hostname,IP  # comment
        host_record_pattern = r'host-record=([^,]+),([^\s#]+)(?:\s*#\s*(.+))?'
        for match in re.finditer(host_record_pattern, content):
            hostname = match.group(1).strip()
            ip = match.group(2).strip()
            comment = match.group(3).strip() if match.group(3) else ""
            result['host_records'].append({
                'hostname': hostname,
                'ip': ip,
                'comment': comment
            })
        
    except Exception as e:
        logger.error(f"Error parsing dnsmasq config file {config_path}: {e}", exc_info=True)
    
    return result


async def sync_dnsmasq_config_to_database(
    session: AsyncSession,
    network: str,
    config_paths: Optional[List[str]] = None
) -> Tuple[int, int]:
    """Sync DNS records from dnsmasq config files to database
    
    Args:
        session: Database session
        network: Network name ("homelab" or "lan")
        config_paths: Optional list of config file paths to parse.
                     If None, uses default paths for the network.
        
    Returns:
        Tuple of (zones_created_or_updated, records_created_or_updated)
    """
    if network not in ['homelab', 'lan']:
        raise ValueError(f"Invalid network: {network}. Must be 'homelab' or 'lan'")
    
    if config_paths is None:
        # Default paths: main config + webui config
        base_path = f"/var/lib/dnsmasq/{network}"
        config_paths = [
            f"{base_path}/dnsmasq.conf",
            f"{base_path}/webui-dns.conf"
        ]
    
    # Parse all config files
    all_authoritative = set()
    all_wildcards = {}
    all_host_records = {}
    
    for config_path in config_paths:
        parsed = parse_dnsmasq_config_file(config_path)
        
        # Collect authoritative domains
        all_authoritative.update(parsed['authoritative'])
        
        # Collect wildcards (domain -> {ip, comment})
        for wildcard in parsed['wildcards']:
            domain = wildcard['domain']
            # If domain already exists, prefer the one with a comment or keep first
            if domain not in all_wildcards or (wildcard['comment'] and not all_wildcards[domain].get('comment')):
                all_wildcards[domain] = wildcard
        
        # Collect host records (hostname -> {ip, comment})
        for record in parsed['host_records']:
            hostname = record['hostname']
            # If hostname already exists, prefer the one with a comment or keep first
            if hostname not in all_host_records or (record['comment'] and not all_host_records[hostname].get('comment')):
                all_host_records[hostname] = record
    
    zones_updated = 0
    records_updated = 0
    
    # Process authoritative domains and wildcards to determine zones
    # A zone is typically the base domain (e.g., "jeandr.net")
    zones_to_create = set()
    
    # Add zones from authoritative domains
    for domain in all_authoritative:
        zones_to_create.add(domain)
    
    # Add zones from wildcards (extract base domain)
    for domain in all_wildcards.keys():
        zones_to_create.add(domain)
    
    # Add zones from host records (extract base domain)
    for hostname in all_host_records.keys():
        parts = hostname.split('.')
        if len(parts) >= 2:
            base_domain = '.'.join(parts[-2:])
            zones_to_create.add(base_domain)
    
    # Create or update zones
    for zone_name in zones_to_create:
        # Check if zone exists
        result = await session.execute(
            select(DnsZoneDB)
            .where(DnsZoneDB.name == zone_name, DnsZoneDB.network == network)
        )
        zone = result.scalar_one_or_none()
        
        if not zone:
            # Create new zone
            zone = DnsZoneDB(
                name=zone_name,
                network=network,
                authoritative=zone_name in all_authoritative or zone_name in all_wildcards,
                enabled=True
            )
            session.add(zone)
            await session.flush()
            zones_updated += 1
            logger.debug(f"Created zone: {zone_name} for network {network}")
        else:
            # Update existing zone
            zone.authoritative = zone_name in all_authoritative or zone_name in all_wildcards
            zones_updated += 1
    
    await session.flush()
    
    # Create or update records
    for zone_name in zones_to_create:
        # Get zone
        result = await session.execute(
            select(DnsZoneDB)
            .where(DnsZoneDB.name == zone_name, DnsZoneDB.network == network)
        )
        zone = result.scalar_one_or_none()
        if not zone:
            continue
        
        # Process wildcards for this zone
        if zone_name in all_wildcards:
            wildcard = all_wildcards[zone_name]
            wildcard_name = f"*.{zone_name}"
            
            # Check if wildcard record exists
            result = await session.execute(
                select(DnsRecordDB)
                .where(
                    DnsRecordDB.zone_id == zone.id,
                    DnsRecordDB.name == wildcard_name
                )
            )
            record = result.scalar_one_or_none()
            
            if not record:
                # Create as CNAME pointing to base domain
                record = DnsRecordDB(
                    zone_id=zone.id,
                    name=wildcard_name,
                    type='CNAME',
                    value=zone_name,
                    comment=wildcard.get('comment', ''),
                    enabled=True
                )
                session.add(record)
                records_updated += 1
            else:
                # Update existing record
                if record.type != 'CNAME' or record.value != zone_name:
                    record.type = 'CNAME'
                    record.value = zone_name
                    if wildcard.get('comment'):
                        record.comment = wildcard['comment']
                    records_updated += 1
        
        # Process host records for this zone
        for hostname, record_data in all_host_records.items():
            # Check if this hostname belongs to this zone
            if not hostname.endswith(f".{zone_name}") and hostname != zone_name:
                continue
            
            # Check if record exists
            result = await session.execute(
                select(DnsRecordDB)
                .where(
                    DnsRecordDB.zone_id == zone.id,
                    DnsRecordDB.name == hostname
                )
            )
            record = result.scalar_one_or_none()
            
            if not record:
                # Create new A record
                record = DnsRecordDB(
                    zone_id=zone.id,
                    name=hostname,
                    type='A',
                    value=record_data['ip'],
                    comment=record_data.get('comment', ''),
                    enabled=True
                )
                session.add(record)
                records_updated += 1
            else:
                # Update existing record
                if record.type != 'A' or record.value != record_data['ip']:
                    record.type = 'A'
                    record.value = record_data['ip']
                    if record_data.get('comment'):
                        record.comment = record_data['comment']
                    records_updated += 1
    
    await session.commit()
    
    logger.info(f"Synced {zones_updated} zones and {records_updated} records from dnsmasq configs for network {network}")
    
    return zones_updated, records_updated

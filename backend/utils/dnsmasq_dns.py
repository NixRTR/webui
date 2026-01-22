"""
Generate dnsmasq DNS configuration from database records
"""
import logging
from typing import Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import DnsZoneDB, DnsRecordDB

logger = logging.getLogger(__name__)


async def generate_dnsmasq_dns_config(session: AsyncSession, network: str) -> str:
    """Generate dnsmasq DNS configuration from database records
    
    Args:
        session: Database session
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
    
    # Get all enabled zones for this network
    result = await session.execute(
        select(DnsZoneDB)
        .where(DnsZoneDB.network == network, DnsZoneDB.enabled == True)
        .order_by(DnsZoneDB.name)
    )
    zones = result.scalars().all()
    
    if not zones:
        logger.debug(f"No enabled zones found for network {network}")
        return "\n".join(lines)
    
    # Collect wildcards and host records
    wildcards = []  # List of {domain, ip, comment}
    host_records = []  # List of {hostname, ip, comment}
    authoritative_domains = set()  # Domains that should have local= directive
    
    for zone in zones:
        # Get all enabled records for this zone
        result = await session.execute(
            select(DnsRecordDB)
            .where(DnsRecordDB.zone_id == zone.id, DnsRecordDB.enabled == True)
            .order_by(DnsRecordDB.name)
        )
        records = result.scalars().all()
        
        # Check if zone is authoritative
        if zone.authoritative:
            authoritative_domains.add(zone.name)
        
        # Process records
        for record in records:
            if record.type == 'A':
                # Check if this is a wildcard
                if record.name.startswith('*.'):
                    # Extract domain (remove *. prefix)
                    domain = record.name[2:]  # Remove "*."
                    wildcards.append({
                        'domain': domain,
                        'ip': record.value,
                        'comment': record.comment or ""
                    })
                else:
                    # Regular A record
                    host_records.append({
                        'hostname': record.name,
                        'ip': record.value,
                        'comment': record.comment or ""
                    })
            elif record.type == 'CNAME':
                # For CNAME, we need to resolve the target to an IP
                # First check if target is a wildcard
                if record.name.startswith('*.'):
                    domain = record.name[2:]  # Remove "*."
                    # Try to find the target's IP
                    target_ip = await _resolve_cname_target(session, record.value, network)
                    if target_ip:
                        wildcards.append({
                            'domain': domain,
                            'ip': target_ip,
                            'comment': record.comment or ""
                        })
                else:
                    # Regular CNAME - resolve to IP
                    target_ip = await _resolve_cname_target(session, record.value, network)
                    if target_ip:
                        host_records.append({
                            'hostname': record.name,
                            'ip': target_ip,
                            'comment': record.comment or ""
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


async def _resolve_cname_target(session: AsyncSession, target: str, network: str) -> Optional[str]:
    """Resolve a CNAME target to an IP address
    
    Args:
        session: Database session
        target: Target hostname from CNAME record
        network: Network name
        
    Returns:
        IP address if found, None otherwise
    """
    # First, try to find an A record with this exact name
    result = await session.execute(
        select(DnsRecordDB)
        .join(DnsZoneDB, DnsRecordDB.zone_id == DnsZoneDB.id)
        .where(
            DnsZoneDB.network == network,
            DnsRecordDB.name == target,
            DnsRecordDB.type == 'A',
            DnsRecordDB.enabled == True
        )
        .limit(1)
    )
    a_record = result.scalar_one_or_none()
    if a_record:
        return a_record.value
    
    # If not found, try to extract base domain and check for wildcard
    parts = target.split('.')
    if len(parts) >= 2:
        base_domain = '.'.join(parts[-2:])
        # Check for wildcard record
        wildcard_name = f"*.{base_domain}"
        result = await session.execute(
            select(DnsRecordDB)
            .join(DnsZoneDB, DnsRecordDB.zone_id == DnsZoneDB.id)
            .where(
                DnsZoneDB.network == network,
                DnsRecordDB.name == wildcard_name,
                DnsRecordDB.type == 'A',
                DnsRecordDB.enabled == True
            )
            .limit(1)
        )
        wildcard_record = result.scalar_one_or_none()
        if wildcard_record:
            return wildcard_record.value
    
    # Could also check CNAME chains, but for simplicity, return None if not found
    logger.debug(f"Could not resolve CNAME target {target} to IP for network {network}")
    return None

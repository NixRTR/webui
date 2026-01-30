"""
Utility for writing Nix configuration files
Handles formatting Python data structures as valid Nix syntax
"""
import logging
from typing import Dict, List, Optional, Any
import json

logger = logging.getLogger(__name__)


def escape_nix_string(s: str) -> str:
    """Escape special characters in a Nix string"""
    # Replace backslashes first
    s = s.replace('\\', '\\\\')
    # Replace double quotes
    s = s.replace('"', '\\"')
    # Replace newlines
    s = s.replace('\n', '\\n')
    # Replace dollar signs (to prevent interpolation)
    s = s.replace('$', '\\$')
    return s


def format_nix_string(value: str, indent: int = 0) -> str:
    """Format a string as a Nix string literal"""
    escaped = escape_nix_string(value)
    return f'"{escaped}"'


def format_nix_list(items: List[Any], indent: int = 0) -> str:
    """Format a Python list as a Nix list"""
    if not items:
        return "[]"
    
    indent_str = "  " * indent
    lines = ["["]
    for i, item in enumerate(items):
        if isinstance(item, dict):
            item_str = format_nix_dict(item, indent + 1)
        elif isinstance(item, list):
            item_str = format_nix_list(item, indent + 1)
        elif isinstance(item, str):
            item_str = format_nix_string(item)
        elif isinstance(item, (int, float, bool)):
            item_str = json.dumps(item)
        else:
            item_str = json.dumps(item)
        
        # In Nix, list items are space-separated, not semicolon-separated
        # Semicolons are only used within attribute sets (dicts), not between list items
        lines.append(f"{indent_str}  {item_str}")
    lines.append(f"{indent_str}]")
    return "\n".join(lines)


def format_nix_dict(data: Dict[str, Any], indent: int = 0) -> str:
    """Format a Python dict as a Nix attribute set"""
    if not data:
        return "{}"
    
    indent_str = "  " * indent
    lines = ["{"]
    items = sorted(data.items())
    for i, (key, value) in enumerate(items):
        # Format the key (quote if needed)
        if not key.replace('_', '').replace('-', '').isalnum():
            nix_key = f'"{escape_nix_string(key)}"'
        else:
            nix_key = key
        
        # Format the value
        if isinstance(value, dict):
            value_str = format_nix_dict(value, indent + 1)
        elif isinstance(value, list):
            value_str = format_nix_list(value, indent + 1)
        elif isinstance(value, str):
            value_str = format_nix_string(value)
        elif isinstance(value, (int, float, bool)):
            value_str = json.dumps(value)
        elif value is None:
            value_str = "null"
        else:
            value_str = json.dumps(value)
        
        # In Nix, attribute assignments are terminated by semicolons; include for all for strict parsers
        suffix = ";"
        lines.append(f"{indent_str}  {nix_key} = {value_str}{suffix}")
    lines.append(f"{indent_str}}}")
    return "\n".join(lines)


def write_dns_nix_file(
    network: str,
    a_records: Dict[str, Dict[str, str]],
    cname_records: Dict[str, Dict[str, str]],
    file_path: str
) -> None:
    """Write DNS records to a Nix file
    
    Args:
        network: Network name ("homelab" or "lan")
        a_records: Dictionary mapping hostname -> {ip, comment}
        cname_records: Dictionary mapping hostname -> {target, comment}
        file_path: Path to write the Nix file
    """
    # Build the Nix structure
    nix_data = {
        "a_records": a_records,
        "cname_records": cname_records
    }
    
    # Format as Nix
    nix_content = format_nix_dict(nix_data, indent=0)
    
    # Write to file (atomic write)
    import tempfile
    import os
    import shutil
    
    # Write to temp file first
    dirname = os.path.dirname(file_path)
    os.makedirs(dirname, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(mode='w', dir=dirname, delete=False, suffix='.nix') as f:
        temp_path = f.name
        f.write(nix_content)
        f.write("\n")
    
    # Atomic rename
    shutil.move(temp_path, file_path)
    os.chmod(file_path, 0o644)
    
    logger.info(f"Wrote DNS Nix file for {network} to {file_path}")


def write_dhcp_nix_file(
    network: str,
    enable: bool,
    start: str,
    end: str,
    leaseTime: str,
    dnsServers: List[str],
    dynamicDomain: str,
    reservations: List[Dict[str, str]],
    file_path: str
) -> None:
    """Write DHCP configuration to a Nix file
    
    Args:
        network: Network name ("homelab" or "lan")
        enable: Whether DHCP is enabled
        start: Start IP address
        end: End IP address
        leaseTime: Lease time string
        dnsServers: List of DNS server IPs
        dynamicDomain: Dynamic DNS domain (or empty string)
        reservations: List of reservation dicts with hostname, hwAddress, ipAddress, comment
        file_path: Path to write the Nix file
    """
    # Build the Nix structure
    nix_data = {
        "enable": enable,
        "start": start,
        "end": end,
        "leaseTime": leaseTime,
        "dnsServers": dnsServers,
        "dynamicDomain": dynamicDomain,
        "reservations": reservations
    }
    
    # Format as Nix
    nix_content = format_nix_dict(nix_data, indent=0)
    
    # Write to file (atomic write)
    import tempfile
    import os
    import shutil
    
    # Write to temp file first
    dirname = os.path.dirname(file_path)
    os.makedirs(dirname, exist_ok=True)
    
    with tempfile.NamedTemporaryFile(mode='w', dir=dirname, delete=False, suffix='.nix') as f:
        temp_path = f.name
        f.write(nix_content)
        f.write("\n")
    
    # Atomic rename
    shutil.move(temp_path, file_path)
    os.chmod(file_path, 0o644)
    
    logger.info(f"Wrote DHCP Nix file for {network} to {file_path}")


def write_cake_nix_file(
    enable: bool,
    aggressiveness: str,
    uploadBandwidth: Optional[str] = None,
    downloadBandwidth: Optional[str] = None,
    file_path: str = None
) -> str:
    """Format CAKE configuration as Nix dict
    
    Args:
        enable: Whether CAKE is enabled
        aggressiveness: Aggressiveness level ("auto", "conservative", "moderate", "aggressive")
        uploadBandwidth: Optional upload bandwidth (e.g., "190Mbit")
        downloadBandwidth: Optional download bandwidth (e.g., "475Mbit")
        file_path: Optional file path (not used, returns formatted string)
        
    Returns:
        Formatted Nix content as string
    """
    nix_data = {
        "enable": enable,
        "aggressiveness": aggressiveness
    }
    
    if uploadBandwidth:
        nix_data["uploadBandwidth"] = uploadBandwidth
    if downloadBandwidth:
        nix_data["downloadBandwidth"] = downloadBandwidth
    
    return format_nix_dict(nix_data, indent=0)


def write_apprise_nix_file(
    enable: bool,
    port: int,
    attachSize: int,
    services: Dict[str, Dict],
    file_path: str = None
) -> str:
    """Format Apprise configuration as Nix dict
    
    Args:
        enable: Whether Apprise is enabled
        port: Port number
        attachSize: Maximum attachment size in MB
        services: Dictionary of service configurations
        file_path: Optional file path (not used, returns formatted string)
        
    Returns:
        Formatted Nix content as string
    """
    nix_data = {
        "enable": enable,
        "port": port,
        "attachSize": attachSize,
        "services": services
    }
    
    return format_nix_dict(nix_data, indent=0)


def write_dyndns_nix_file(
    enable: bool,
    provider: str,
    domain: str,
    subdomain: str,
    domainId: int,
    recordId: int,
    checkInterval: str,
    file_path: str = None
) -> str:
    """Format Dynamic DNS configuration as Nix dict
    
    Args:
        enable: Whether Dynamic DNS is enabled
        provider: Provider name (e.g., "linode")
        domain: Domain name
        subdomain: Subdomain (may be empty string)
        domainId: Domain ID
        recordId: Record ID
        checkInterval: Check interval (e.g., "5m")
        file_path: Optional file path (not used, returns formatted string)
        
    Returns:
        Formatted Nix content as string
    """
    nix_data = {
        "enable": enable,
        "provider": provider,
        "domain": domain,
        "subdomain": subdomain,
        "domainId": domainId,
        "recordId": recordId,
        "checkInterval": checkInterval
    }
    
    return format_nix_dict(nix_data, indent=0)


def write_port_forwarding_nix_file(
    rules: List[Dict[str, Any]],
    file_path: str = None
) -> str:
    """Format Port Forwarding configuration as Nix list
    
    Args:
        rules: List of rule dictionaries with proto, externalPort, destination, destinationPort
        file_path: Optional file path (not used, returns formatted string)
        
    Returns:
        Formatted Nix content as string
    """
    return format_nix_list(rules, indent=0)


def write_blocklists_nix_file(
    network: str,
    enable: bool,
    blocklists: Dict[str, Dict[str, Any]],
    file_path: str = None
) -> str:
    """Format Blocklists configuration as Nix dict
    
    Args:
        network: Network name ("homelab" or "lan")
        enable: Master enable switch
        blocklists: Dictionary of blocklist_name -> {enable, url, description, updateInterval}
        file_path: Optional file path (not used, returns formatted string)
        
    Returns:
        Formatted Nix content as string
    """
    nix_data = {
        "enable": enable,
        **blocklists
    }
    
    return format_nix_dict(nix_data, indent=0)


def write_whitelist_nix_file(
    network: str,
    domains: List[str],
    file_path: str = None
) -> str:
    """Format Whitelist configuration as Nix list
    
    Args:
        network: Network name ("homelab" or "lan")
        domains: List of domain strings
        file_path: Optional file path (not used, returns formatted string)
        
    Returns:
        Formatted Nix content as string
    """
    return format_nix_list(domains, indent=0)

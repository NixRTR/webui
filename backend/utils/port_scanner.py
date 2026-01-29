"""
Port scanning utility using nmap
"""
import os
import subprocess
import xml.etree.ElementTree as ET
import logging
from typing import Dict, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


def find_nmap() -> Optional[str]:
    """Find nmap binary in common locations
    
    Checks NMAP_BIN environment variable first (set by NixOS module),
    then falls back to common system paths.
    """
    # Check environment variable first (set by NixOS module)
    env_path = os.environ.get("NMAP_BIN")
    if env_path:
        try:
            p = subprocess.run([env_path, '-V'], capture_output=True, text=True, timeout=2)
            if p.returncode == 0:
                return env_path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    
    common_paths = ['/usr/bin/nmap', '/usr/local/bin/nmap', 'nmap']
    for path in common_paths:
        try:
            p = subprocess.run([path, '-V'], capture_output=True, text=True, timeout=2)
            if p.returncode == 0:
                return path
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def parse_nmap_xml(xml_output: str) -> Dict:
    """Parse nmap XML output into structured data
    
    Returns:
        Dict with keys:
            - ports: List of port info dicts with keys: port, state, service_name, service_version, service_product, service_extrainfo, protocol
            - scan_info: Dict with scan metadata
    """
    try:
        root = ET.fromstring(xml_output)
        ports = []
        
        # Find all hosts
        for host in root.findall('.//host'):
            # Find all ports
            for port_elem in host.findall('.//port'):
                port_info = {
                    'port': int(port_elem.get('portid')),
                    'protocol': port_elem.get('protocol', 'tcp'),
                    'state': 'unknown',
                    'service_name': None,
                    'service_version': None,
                    'service_product': None,
                    'service_extrainfo': None,
                }
                
                # Get port state
                state_elem = port_elem.find('state')
                if state_elem is not None:
                    port_info['state'] = state_elem.get('state', 'unknown')
                
                # Get service information
                service_elem = port_elem.find('service')
                if service_elem is not None:
                    port_info['service_name'] = service_elem.get('name')
                    port_info['service_version'] = service_elem.get('version')
                    port_info['service_product'] = service_elem.get('product')
                    port_info['service_extrainfo'] = service_elem.get('extrainfo')
                
                ports.append(port_info)
        
        # Get scan info
        scan_info = {
            'scan_start': None,
            'scan_end': None,
        }
        
        runstats = root.find('.//runstats')
        if runstats is not None:
            finished = runstats.find('finished')
            if finished is not None:
                scan_info['scan_start'] = finished.get('startstr')
                scan_info['scan_end'] = finished.get('endstr')
        
        return {
            'ports': ports,
            'scan_info': scan_info,
        }
    except ET.ParseError as e:
        logger.error(f"Failed to parse nmap XML output: {e}")
        raise ValueError(f"Invalid XML output from nmap: {e}")
    except Exception as e:
        logger.error(f"Unexpected error parsing nmap output: {e}")
        raise


def scan_device_ports(ip_address: str, mac_address: str, timeout: int = 300) -> Dict:
    """Scan device ports using nmap
    
    Args:
        ip_address: Target IP address
        mac_address: Device MAC address (for logging)
        timeout: Maximum scan time in seconds (default 5 minutes)
    
    Returns:
        Dict with keys:
            - ports: List of port info dicts
            - scan_info: Scan metadata
            - success: bool indicating if scan completed successfully
            - error: Optional error message
    
    Raises:
        FileNotFoundError: If nmap is not found
        ValueError: If IP address is invalid
        subprocess.TimeoutExpired: If scan exceeds timeout
    """
    nmap_path = find_nmap()
    if not nmap_path:
        raise FileNotFoundError("nmap not found. Please install nmap.")
    
    # Validate IP address (basic check)
    if not ip_address or not isinstance(ip_address, str):
        raise ValueError(f"Invalid IP address: {ip_address}")
    
    logger.info(f"Starting port scan for device {mac_address} at {ip_address}")
    
    # Build nmap command
    # -F: Fast scan (top 100 ports) - but we want top 1000, so use --top-ports 1000
    # -sV: Version detection
    # -oX -: Output XML to stdout
    # -T4: Aggressive timing template
    cmd = [
        nmap_path,
        '--top-ports', '1000',
        '-sV',
        '-T4',
        '-oX', '-',
        ip_address
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False  # Don't raise on non-zero exit code
        )
        
        if result.returncode != 0:
            error_msg = result.stderr or f"nmap exited with code {result.returncode}"
            logger.error(f"nmap scan failed for {ip_address}: {error_msg}")
            return {
                'ports': [],
                'scan_info': {},
                'success': False,
                'error': error_msg
            }
        
        # Parse XML output
        parsed = parse_nmap_xml(result.stdout)
        
        logger.info(f"Port scan completed for {mac_address} at {ip_address}: found {len(parsed['ports'])} ports")
        
        return {
            **parsed,
            'success': True,
            'error': None
        }
        
    except subprocess.TimeoutExpired:
        logger.error(f"Port scan timeout for {ip_address} after {timeout} seconds")
        return {
            'ports': [],
            'scan_info': {},
            'success': False,
            'error': f"Scan timeout after {timeout} seconds"
        }
    except Exception as e:
        logger.error(f"Unexpected error during port scan for {ip_address}: {e}")
        return {
            'ports': [],
            'scan_info': {},
            'success': False,
            'error': str(e)
        }

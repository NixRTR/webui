"""
Parser for Dynamic DNS Nix configuration file (config/dyndns.nix)
"""
import os
import logging
import re
from typing import Dict, Optional
from ..config import settings

logger = logging.getLogger(__name__)


def parse_dyndns_nix_file() -> Optional[Dict]:
    """Parse Dynamic DNS Nix configuration file
    
    Returns:
        Dictionary with Dynamic DNS configuration:
        - enable: bool
        - provider: str (e.g., "linode")
        - domain: str
        - subdomain: str (may be empty)
        - domainId: int
        - recordId: int
        - checkInterval: str (e.g., "5m")
    """
    file_path = settings.dyndns_config_file
    
    if not os.path.exists(file_path):
        logger.warning(f"Dynamic DNS Nix file not found at {file_path}")
        return None
    
    logger.debug(f"Parsing Dynamic DNS Nix file: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        config = {
            'enable': True,  # Default
            'provider': '',
            'domain': '',
            'subdomain': '',
            'domainId': 0,
            'recordId': 0,
            'checkInterval': '5m'
        }
        
        # Extract enable
        enable_match = re.search(r'enable\s*=\s*(true|false)', content)
        if enable_match:
            config['enable'] = enable_match.group(1) == 'true'
        
        # Extract provider
        provider_match = re.search(r'provider\s*=\s*"([^"]+)"', content)
        if provider_match:
            config['provider'] = provider_match.group(1)
        
        # Extract domain
        domain_match = re.search(r'domain\s*=\s*"([^"]+)"', content)
        if domain_match:
            config['domain'] = domain_match.group(1)
        
        # Extract subdomain (may be empty)
        subdomain_match = re.search(r'subdomain\s*=\s*"([^"]*)"', content)
        if subdomain_match:
            config['subdomain'] = subdomain_match.group(1)
        
        # Extract domainId
        domain_id_match = re.search(r'domainId\s*=\s*(\d+)', content)
        if domain_id_match:
            config['domainId'] = int(domain_id_match.group(1))
        
        # Extract recordId
        record_id_match = re.search(r'recordId\s*=\s*(\d+)', content)
        if record_id_match:
            config['recordId'] = int(record_id_match.group(1))
        
        # Extract checkInterval
        interval_match = re.search(r'checkInterval\s*=\s*"([^"]+)"', content)
        if interval_match:
            config['checkInterval'] = interval_match.group(1)
        
        logger.debug(f"Parsed Dynamic DNS config: enable={config['enable']}, provider={config['provider']}")
        return config
        
    except Exception as e:
        logger.error(f"Error parsing Dynamic DNS Nix file {file_path}: {type(e).__name__}: {str(e)}", exc_info=True)
        return None

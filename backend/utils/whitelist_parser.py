"""
Parser for DNS Whitelist Nix configuration files (config/dnsmasq/whitelist-{network}.nix)
"""
import os
import logging
import re
from typing import List, Optional
from ..config import settings

logger = logging.getLogger(__name__)


def parse_whitelist_nix_file(network: str) -> Optional[List[str]]:
    """Parse Whitelist Nix file for a specific network
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        List of whitelisted domain strings
    """
    # Determine file path
    if network == "homelab":
        file_path = settings.whitelist_homelab_file
    elif network == "lan":
        file_path = settings.whitelist_lan_file
    else:
        logger.error(f"Invalid network: {network}")
        return None
    
    if not os.path.exists(file_path):
        logger.warning(f"Whitelist Nix file not found at {file_path}")
        return None
    
    logger.debug(f"Parsing Whitelist Nix file: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        domains = []
        
        # Extract array content
        array_match = re.search(r'\[\s*(.*?)\s*\]', content, re.DOTALL)
        if array_match:
            array_content = array_match.group(1)
            # Extract quoted strings (domains)
            domain_pattern = r'"([^"]+)"'
            for match in re.finditer(domain_pattern, array_content):
                domain = match.group(1)
                # Skip commented-out lines
                line_start = array_content.rfind('\n', 0, match.start()) + 1
                line_prefix = array_content[line_start:match.start()].strip()
                if not line_prefix.startswith('#'):
                    domains.append(domain)
        
        logger.debug(f"Parsed Whitelist config for {network}: {len(domains)} domains")
        return domains
        
    except Exception as e:
        logger.error(f"Error parsing Whitelist Nix file {file_path}: {type(e).__name__}: {str(e)}", exc_info=True)
        return None

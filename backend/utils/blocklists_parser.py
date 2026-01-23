"""
Parser for DNS Blocklists Nix configuration files (config/dnsmasq/blocklists-{network}.nix)
"""
import os
import logging
import re
from typing import Dict, Optional
from ..config import settings

logger = logging.getLogger(__name__)


def parse_blocklists_nix_file(network: str) -> Optional[Dict]:
    """Parse Blocklists Nix file for a specific network
    
    Args:
        network: Network name ("homelab" or "lan")
        
    Returns:
        Dictionary with blocklists configuration:
        - enable: bool (master switch)
        - blocklists: dict of blocklist_name -> {enable, url, description, updateInterval}
    """
    # Determine file path
    if network == "homelab":
        file_path = settings.blocklists_homelab_file
    elif network == "lan":
        file_path = settings.blocklists_lan_file
    else:
        logger.error(f"Invalid network: {network}")
        return None
    
    if not os.path.exists(file_path):
        logger.warning(f"Blocklists Nix file not found at {file_path}")
        return None
    
    logger.debug(f"Parsing Blocklists Nix file: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        config = {
            'enable': True,  # Default
            'blocklists': {}
        }
        
        # Extract master enable
        enable_match = re.search(r'enable\s*=\s*(true|false)', content)
        if enable_match:
            config['enable'] = enable_match.group(1) == 'true'
        
        # Extract blocklists (nested structure)
        # Find each blocklist entry: blocklist_name = { enable = true; url = "..."; ... }
        blocklist_pattern = r'(\w+(?:-\w+)*)\s*=\s*\{'
        
        for match in re.finditer(blocklist_pattern, content):
            blocklist_name = match.group(1)
            brace_start = match.end() - 1
            blocklist_content, _ = _extract_braced_content(content, brace_start)
            
            if blocklist_content:
                # Skip commented-out lines
                line_start = content.rfind('\n', 0, match.start()) + 1
                line_prefix = content[line_start:match.start()].strip()
                if line_prefix.startswith('#'):
                    continue
                
                blocklist_config = _parse_blocklist_item(blocklist_content)
                if blocklist_config:
                    config['blocklists'][blocklist_name] = blocklist_config
        
        logger.debug(f"Parsed Blocklists config for {network}: {len(config['blocklists'])} blocklists")
        return config
        
    except Exception as e:
        logger.error(f"Error parsing Blocklists Nix file {file_path}: {type(e).__name__}: {str(e)}", exc_info=True)
        return None


def _extract_braced_content(text: str, start_pos: int) -> tuple[Optional[str], int]:
    """Extract content between matching braces"""
    if start_pos >= len(text) or text[start_pos] != '{':
        return None, start_pos
    depth = 0
    start = start_pos + 1
    i = start_pos
    while i < len(text):
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return text[start:i].strip(), i + 1
        i += 1
    return None, start_pos


def _parse_blocklist_item(content: str) -> Optional[Dict]:
    """Parse individual blocklist configuration"""
    blocklist = {
        'enable': False,
        'url': '',
        'description': '',
        'updateInterval': '24h'
    }
    
    # Extract enable
    enable_match = re.search(r'enable\s*=\s*(true|false)', content)
    if enable_match:
        blocklist['enable'] = enable_match.group(1) == 'true'
    
    # Extract url
    url_match = re.search(r'url\s*=\s*"([^"]+)"', content)
    if url_match:
        blocklist['url'] = url_match.group(1)
    
    # Extract description
    desc_match = re.search(r'description\s*=\s*"([^"]+)"', content)
    if desc_match:
        blocklist['description'] = desc_match.group(1)
    
    # Extract updateInterval
    interval_match = re.search(r'updateInterval\s*=\s*"([^"]+)"', content)
    if interval_match:
        blocklist['updateInterval'] = interval_match.group(1)
    
    return blocklist

"""
Parser for Port Forwarding Nix configuration file (config/port-forwarding.nix)
"""
import os
import logging
import re
from typing import Dict, List, Optional
from ..config import settings

logger = logging.getLogger(__name__)


def parse_port_forwarding_nix_file() -> Optional[List[Dict]]:
    """Parse Port Forwarding Nix configuration file
    
    Returns:
        List of port forwarding rule dictionaries:
        - proto: str ("both", "tcp", "udp")
        - externalPort: int
        - destination: str (IP address)
        - destinationPort: int
    """
    file_path = settings.port_forwarding_config_file
    
    if not os.path.exists(file_path):
        logger.warning(f"Port Forwarding Nix file not found at {file_path}")
        return None
    
    logger.debug(f"Parsing Port Forwarding Nix file: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        rules = []
        
        # Extract array content
        array_match = re.search(r'\[\s*(.*?)\s*\]', content, re.DOTALL)
        if array_match:
            array_content = array_match.group(1)
            rules = _parse_port_forwarding_rules(array_content)
        
        logger.debug(f"Parsed Port Forwarding config: {len(rules)} rules")
        return rules
        
    except Exception as e:
        logger.error(f"Error parsing Port Forwarding Nix file {file_path}: {type(e).__name__}: {str(e)}", exc_info=True)
        return None


def _parse_port_forwarding_rules(content: str) -> List[Dict]:
    """Parse port forwarding rules from array content
    
    Args:
        content: Content between [ ... ]
        
    Returns:
        List of rule dictionaries
    """
    rules = []
    
    # Pattern to match: { proto = "both"; externalPort = 80; destination = "192.168.2.33"; destinationPort = 80; }
    pattern = r'\{\s*proto\s*=\s*"([^"]+)";\s*externalPort\s*=\s*(\d+);\s*destination\s*=\s*"([^"]+)";\s*destinationPort\s*=\s*(\d+);\s*\}'
    
    for match in re.finditer(pattern, content, re.DOTALL):
        # Skip commented-out lines
        line_start = content.rfind('\n', 0, match.start()) + 1
        line_prefix = content[line_start:match.start()].strip()
        if line_prefix.startswith('#'):
            continue
        
        rules.append({
            'proto': match.group(1),
            'externalPort': int(match.group(2)),
            'destination': match.group(3),
            'destinationPort': int(match.group(4))
        })
    
    return rules

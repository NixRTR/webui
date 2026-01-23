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
        
        # Extract array content - match from [ to ] including nested braces
        # Use a more robust approach: find all attribute sets within the array
        # First, find the array boundaries
        array_start = content.find('[')
        array_end = content.rfind(']')
        
        if array_start == -1 or array_end == -1 or array_start >= array_end:
            logger.warning("Could not find array boundaries in port forwarding file")
            return []
        
        array_content = content[array_start + 1:array_end]
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
    
    # Find all attribute sets by matching braces
    # This handles multiline format and nested structures
    i = 0
    while i < len(content):
        # Find the start of an attribute set
        brace_start = content.find('{', i)
        if brace_start == -1:
            break
        
        # Check if this line is commented out
        line_start = content.rfind('\n', 0, brace_start) + 1
        line_prefix = content[line_start:brace_start].strip()
        if line_prefix.startswith('#'):
            i = brace_start + 1
            continue
        
        # Find matching closing brace
        depth = 0
        brace_end = -1
        for j in range(brace_start, len(content)):
            if content[j] == '{':
                depth += 1
            elif content[j] == '}':
                depth -= 1
                if depth == 0:
                    brace_end = j
                    break
        
        if brace_end == -1:
            # No matching brace found, skip
            i = brace_start + 1
            continue
        
        # Extract the attribute set content
        attr_content = content[brace_start + 1:brace_end]
        
        # Extract individual fields (order-independent)
        proto_match = re.search(r'proto\s*=\s*"([^"]+)"', attr_content)
        external_port_match = re.search(r'externalPort\s*=\s*(\d+)', attr_content)
        destination_match = re.search(r'destination\s*=\s*"([^"]+)"', attr_content)
        destination_port_match = re.search(r'destinationPort\s*=\s*(\d+)', attr_content)
        
        # All fields must be present
        if proto_match and external_port_match and destination_match and destination_port_match:
            rules.append({
                'proto': proto_match.group(1),
                'externalPort': int(external_port_match.group(1)),
                'destination': destination_match.group(1),
                'destinationPort': int(destination_port_match.group(1))
            })
        else:
            logger.warning(f"Skipping incomplete port forwarding rule. Missing fields. Content: {attr_content[:100]}")
        
        # Move past this attribute set
        i = brace_end + 1
    
    return rules

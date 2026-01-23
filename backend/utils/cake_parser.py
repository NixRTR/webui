"""
Parser for CAKE traffic shaping Nix configuration file (config/cake.nix)
"""
import os
import logging
import re
from typing import Dict, Optional
from ..config import settings

logger = logging.getLogger(__name__)


def parse_cake_nix_file() -> Optional[Dict]:
    """Parse CAKE Nix configuration file
    
    Returns:
        Dictionary with CAKE configuration:
        - enable: bool
        - aggressiveness: str ("auto", "conservative", "moderate", "aggressive")
        - uploadBandwidth: str (optional, e.g., "190Mbit")
        - downloadBandwidth: str (optional, e.g., "475Mbit")
    """
    file_path = settings.cake_config_file
    
    if not os.path.exists(file_path):
        logger.warning(f"CAKE Nix file not found at {file_path}")
        return None
    
    logger.debug(f"Parsing CAKE Nix file: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        config = {
            'enable': False,  # Default
            'aggressiveness': 'auto',
            'uploadBandwidth': None,
            'downloadBandwidth': None
        }
        
        # Extract enable
        enable_match = re.search(r'enable\s*=\s*(true|false)', content)
        if enable_match:
            config['enable'] = enable_match.group(1) == 'true'
        
        # Extract aggressiveness
        aggressiveness_match = re.search(r'aggressiveness\s*=\s*"([^"]+)"', content)
        if aggressiveness_match:
            config['aggressiveness'] = aggressiveness_match.group(1)
        
        # Extract uploadBandwidth (optional)
        upload_match = re.search(r'uploadBandwidth\s*=\s*"([^"]+)"', content)
        if upload_match:
            config['uploadBandwidth'] = upload_match.group(1)
        
        # Extract downloadBandwidth (optional)
        download_match = re.search(r'downloadBandwidth\s*=\s*"([^"]+)"', content)
        if download_match:
            config['downloadBandwidth'] = download_match.group(1)
        
        logger.debug(f"Parsed CAKE config: enable={config['enable']}, aggressiveness={config['aggressiveness']}")
        return config
        
    except Exception as e:
        logger.error(f"Error parsing CAKE Nix file {file_path}: {type(e).__name__}: {str(e)}", exc_info=True)
        return None

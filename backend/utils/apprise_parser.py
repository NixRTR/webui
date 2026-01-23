"""
Parser for Apprise Nix configuration file (config/apprise.nix)
"""
import os
import logging
import re
from typing import Dict, Optional
from ..config import settings

logger = logging.getLogger(__name__)


def parse_apprise_nix_file() -> Optional[Dict]:
    """Parse Apprise Nix configuration file
    
    Returns:
        Dictionary with Apprise configuration:
        - enable: bool
        - port: int
        - attachSize: int
        - services: dict with service configs (email, homeAssistant, discord, slack, telegram, ntfy)
    """
    file_path = settings.apprise_config_file
    
    if not os.path.exists(file_path):
        logger.warning(f"Apprise Nix file not found at {file_path}")
        return None
    
    logger.debug(f"Parsing Apprise Nix file: {file_path}")
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        config = {
            'enable': True,  # Default
            'port': 8001,
            'attachSize': 0,
            'services': {}
        }
        
        # Extract top-level enable (must be at the start of the file, before services block)
        # Find the opening brace of the root attribute set
        root_brace_start = content.find('{')
        if root_brace_start == -1:
            logger.error("Could not find root attribute set opening brace")
            return None
        
        # Find the services block more precisely - look for "services = {" pattern
        services_match = re.search(r'services\s*=\s*\{', content)
        if services_match:
            services_pos = services_match.start()
            # Extract top-level section (between root { and services = {)
            top_level_section = content[root_brace_start + 1:services_pos]
        else:
            # If no services block, search from root brace to closing brace
            # Find matching closing brace for root
            brace_depth = 0
            root_brace_end = -1
            for i in range(root_brace_start, len(content)):
                if content[i] == '{':
                    brace_depth += 1
                elif content[i] == '}':
                    brace_depth -= 1
                    if brace_depth == 0:
                        root_brace_end = i
                        break
            if root_brace_end == -1:
                top_level_section = content[root_brace_start + 1:]
            else:
                top_level_section = content[root_brace_start + 1:root_brace_end]
        
        # Search for enable in the top-level section (before services)
        # Match "enable = true" or "enable = false" (with optional semicolon)
        # Use word boundary to avoid matching inside other words
        enable_match = re.search(r'\benable\s*=\s*(true|false)\b', top_level_section, re.IGNORECASE)
        if enable_match:
            config['enable'] = enable_match.group(1).lower() == 'true'
            logger.info(f"Parsed Apprise enable: {enable_match.group(1)} -> {config['enable']}")
        else:
            logger.warning(f"Could not find 'enable' field in top-level section. Using default: {config['enable']}")
            logger.debug(f"Top-level section preview: {top_level_section[:300]}")
        
        # Extract port (also top-level, before services)
        port_match = re.search(r'\bport\s*=\s*(\d+)', top_level_section)
        if port_match:
            config['port'] = int(port_match.group(1))
            logger.debug(f"Found port value: {config['port']}")
        
        # Extract attachSize (also top-level, before services)
        attach_match = re.search(r'\battachSize\s*=\s*(\d+)', top_level_section)
        if attach_match:
            config['attachSize'] = int(attach_match.group(1))
            logger.debug(f"Found attachSize value: {config['attachSize']}")
        
        # Extract services block
        services_match = re.search(r'services\s*=\s*\{', content)
        if services_match:
            brace_start = services_match.end() - 1
            services_content, _ = _extract_braced_content(content, brace_start)
            if services_content:
                config['services'] = _parse_services(services_content)
        
        logger.debug(f"Parsed Apprise config: enable={config['enable']}, {len(config['services'])} services")
        return config
        
    except Exception as e:
        logger.error(f"Error parsing Apprise Nix file {file_path}: {type(e).__name__}: {str(e)}", exc_info=True)
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


def _parse_services(content: str) -> Dict:
    """Parse services block from Apprise config"""
    services = {}
    
    # Service names to look for
    service_names = ['email', 'homeAssistant', 'discord', 'slack', 'telegram', 'ntfy']
    
    for service_name in service_names:
        # Find service block: service_name = { ... }
        pattern = rf'{service_name}\s*=\s*{{'
        match = re.search(pattern, content)
        if match:
            brace_start = match.end() - 1
            service_content, _ = _extract_braced_content(content, brace_start)
            if service_content:
                services[service_name] = _parse_service_config(service_name, service_content)
    
    return services


def _parse_service_config(service_name: str, content: str) -> Dict:
    """Parse individual service configuration"""
    service_config = {'enable': False}
    
    # Extract enable
    enable_match = re.search(r'enable\s*=\s*(true|false)', content)
    if enable_match:
        service_config['enable'] = enable_match.group(1) == 'true'
    
    # Service-specific fields
    if service_name == 'email':
        for field in ['smtpHost', 'smtpPort', 'username', 'to', 'from']:
            match = re.search(rf'{field}\s*=\s*"([^"]+)"', content)
            if match:
                value = match.group(1)
                if field == 'smtpPort':
                    service_config[field] = int(value) if value.isdigit() else value
                else:
                    service_config[field] = value
    
    elif service_name == 'homeAssistant':
        for field in ['host', 'port', 'useHttps']:
            match = re.search(rf'{field}\s*=\s*"([^"]+)"', content)
            if match:
                value = match.group(1)
                if field == 'port':
                    service_config[field] = int(value) if value.isdigit() else value
                elif field == 'useHttps':
                    service_config[field] = value.lower() == 'true'
                else:
                    service_config[field] = value
        # Also check for boolean useHttps
        bool_match = re.search(r'useHttps\s*=\s*(true|false)', content)
        if bool_match:
            service_config['useHttps'] = bool_match.group(1) == 'true'
    
    elif service_name == 'telegram':
        match = re.search(r'chatId\s*=\s*"([^"]+)"', content)
        if match:
            service_config['chatId'] = match.group(1)
    
    elif service_name == 'ntfy':
        for field in ['topic', 'server']:
            match = re.search(rf'{field}\s*=\s*"([^"]+)"', content)
            if match:
                service_config[field] = match.group(1)
    
    # discord and slack have no additional fields (just enable)
    
    return service_config

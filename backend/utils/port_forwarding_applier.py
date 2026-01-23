"""
Apply port forwarding rules from port-forwarding.nix to iptables
This allows immediate application of rules without nixos-rebuild
"""
import os
import subprocess
import logging
from typing import List, Dict, Optional
from .port_forwarding_parser import parse_port_forwarding_nix_file
from ..config import settings

logger = logging.getLogger(__name__)

# Chain name for WebUI-managed port forwarding rules
IPTABLES_CHAIN = "WEBUI_PORT_FORWARD"


def get_wan_interface() -> Optional[str]:
    """Determine the WAN interface (external interface for NAT)
    
    Returns:
        Interface name (e.g., "eno1", "ppp0") or None if not found
    """
    # Try to read from router-config.nix first
    router_config_path = settings.router_config_file
    if os.path.exists(router_config_path):
        try:
            with open(router_config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Look for WAN interface configuration
            # Pattern: wan = { type = "pppoe"; interface = "eno1"; ... }
            import re
            wan_match = re.search(r'wan\s*=\s*\{[^}]*interface\s*=\s*"([^"]+)"', content, re.DOTALL)
            if wan_match:
                wan_interface = wan_match.group(1)
                
                # Check if it's PPPoE (would use ppp0 instead)
                pppoe_match = re.search(r'wan\s*=\s*\{[^}]*type\s*=\s*"pppoe"', content, re.DOTALL)
                if pppoe_match:
                    # For PPPoE, the logical interface is typically ppp0
                    # Check if ppp0 exists
                    if os.path.exists('/sys/class/net/ppp0'):
                        return 'ppp0'
                    # Otherwise use the physical interface
                    return wan_interface
                
                return wan_interface
        except Exception as e:
            logger.warning(f"Could not read WAN interface from router-config.nix: {e}")
    
    # Fallback: determine from default route
    try:
        result = subprocess.run(
            ['ip', 'route', 'show', 'default'],
            capture_output=True,
            text=True,
            check=True
        )
        # Output format: "default via 1.2.3.4 dev eno1"
        parts = result.stdout.strip().split()
        if 'dev' in parts:
            dev_index = parts.index('dev')
            if dev_index + 1 < len(parts):
                return parts[dev_index + 1]
    except Exception as e:
        logger.warning(f"Could not determine WAN interface from routing table: {e}")
    
    return None


def get_internal_interfaces() -> List[str]:
    """Get list of internal bridge interfaces
    
    Returns:
        List of bridge interface names (e.g., ["br0", "br1"])
    """
    interfaces = []
    
    # Read from router-config.nix
    router_config_path = settings.router_config_file
    if os.path.exists(router_config_path):
        try:
            with open(router_config_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Look for bridge names
            # Pattern: bridges = [ { name = "br0"; ... } { name = "br1"; ... } ]
            import re
            bridge_matches = re.findall(r'name\s*=\s*"([^"]+)"', content)
            # Filter to likely bridge names (br0, br1, etc.)
            for match in bridge_matches:
                if match.startswith('br') and match[2:].isdigit():
                    interfaces.append(match)
        except Exception as e:
            logger.warning(f"Could not read bridge interfaces from router-config.nix: {e}")
    
    # Fallback: find all bridge interfaces
    if not interfaces:
        try:
            bridge_dir = '/sys/class/net'
            if os.path.exists(bridge_dir):
                for item in os.listdir(bridge_dir):
                    if item.startswith('br') and os.path.isdir(os.path.join(bridge_dir, item)):
                        interfaces.append(item)
        except Exception as e:
            logger.warning(f"Could not enumerate bridge interfaces: {e}")
    
    return interfaces


def ensure_iptables_chain() -> None:
    """Ensure the WebUI port forwarding chain exists in iptables"""
    try:
        # Check if chain exists
        result = subprocess.run(
            ['iptables', '-t', 'nat', '-L', IPTABLES_CHAIN],
            capture_output=True,
            stderr=subprocess.DEVNULL
        )
        
        if result.returncode != 0:
            # Chain doesn't exist, create it
            subprocess.run(
                ['iptables', '-t', 'nat', '-N', IPTABLES_CHAIN],
                check=True
            )
            logger.info(f"Created iptables chain: {IPTABLES_CHAIN}")
        
        # Ensure the chain is referenced in PREROUTING
        # Check if jump rule exists
        result = subprocess.run(
            ['iptables', '-t', 'nat', '-C', 'PREROUTING', '-j', IPTABLES_CHAIN],
            capture_output=True,
            stderr=subprocess.DEVNULL
        )
        
        if result.returncode != 0:
            # Jump rule doesn't exist, add it (insert at beginning)
            subprocess.run(
                ['iptables', '-t', 'nat', '-I', 'PREROUTING', '1', '-j', IPTABLES_CHAIN],
                check=True
            )
            logger.info(f"Added jump rule from PREROUTING to {IPTABLES_CHAIN}")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to ensure iptables chain: {e}")
        raise


def clear_iptables_chain() -> None:
    """Clear all rules from the WebUI port forwarding chain"""
    try:
        # Flush the chain (remove all rules)
        subprocess.run(
            ['iptables', '-t', 'nat', '-F', IPTABLES_CHAIN],
            check=True,
            stderr=subprocess.DEVNULL  # Ignore error if chain doesn't exist
        )
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to flush iptables chain (may not exist): {e}")


def apply_port_forwarding_rules() -> None:
    """Read port forwarding rules from Nix file and apply them to iptables"""
    try:
        # Get WAN interface
        wan_interface = get_wan_interface()
        if not wan_interface:
            logger.error("Could not determine WAN interface")
            raise RuntimeError("Could not determine WAN interface for port forwarding")
        
        logger.info(f"Using WAN interface: {wan_interface}")
        
        # Get internal interfaces
        internal_interfaces = get_internal_interfaces()
        if not internal_interfaces:
            logger.warning("No internal interfaces found, using default routing")
            internal_interfaces = ['br0']  # Fallback
        
        # Parse rules from Nix file
        rules = parse_port_forwarding_nix_file()
        if rules is None:
            rules = []
        
        logger.info(f"Applying {len(rules)} port forwarding rules")
        
        # Ensure chain exists
        ensure_iptables_chain()
        
        # Clear existing rules
        clear_iptables_chain()
        
        # Apply each rule
        for rule in rules:
            proto = rule['proto']
            external_port = rule['externalPort']
            destination = rule['destination']
            destination_port = rule['destinationPort']
            
            # Handle "both" protocol (apply to both TCP and UDP)
            protocols = ['tcp', 'udp'] if proto == 'both' else [proto]
            
            for protocol in protocols:
                # Add DNAT rule: forward external port to internal destination
                # Format matches NixOS networking.nat.forwardPorts:
                # iptables -t nat -A WEBUI_PORT_FORWARD -p <proto> --dport <external> -j DNAT --to-destination <dest>:<dest_port>
                # Optionally restrict to WAN interface: -i <wan_interface>
                cmd = [
                    'iptables', '-t', 'nat', '-A', IPTABLES_CHAIN,
                    '-p', protocol,
                    '--dport', str(external_port),
                    '-j', 'DNAT',
                    '--to-destination', f"{destination}:{destination_port}"
                ]
                
                # Optionally add interface restriction (uncomment if needed)
                # if wan_interface:
                #     cmd.insert(-2, '-i')
                #     cmd.insert(-2, wan_interface)
                
                try:
                    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
                    logger.debug(f"Applied rule: {protocol}:{external_port} -> {destination}:{destination_port}")
                except subprocess.CalledProcessError as e:
                    error_msg = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
                    logger.error(f"Failed to apply rule {protocol}:{external_port} -> {destination}:{destination_port}: {error_msg}")
                    # Continue with other rules even if one fails
        
        logger.info("Port forwarding rules applied successfully")
        
    except Exception as e:
        logger.error(f"Failed to apply port forwarding rules: {e}", exc_info=True)
        raise

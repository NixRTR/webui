"""
DNS Blocklists configuration API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import logging
import subprocess

from ..api.auth import get_current_user
from ..models import BlocklistsConfig, BlocklistsConfigUpdate
from ..utils.blocklists_parser import parse_blocklists_nix_file
from ..utils.nix_writer import write_blocklists_nix_file
from ..utils.config_writer import write_blocklists_nix_config

logger = logging.getLogger(__name__)

# Map network names to systemd service names
NETWORK_SERVICE_MAP = {
    'homelab': 'dnsmasq-homelab',
    'lan': 'dnsmasq-lan',
}


def _control_service_via_systemctl(service_name: str, action: str) -> None:
    """Control a systemd service via socket-activated helper service (runs as root)
    
    Uses a socket-activated service that runs as root and accepts commands via
    a Unix socket. This follows NixOS best practices by avoiding direct sudo
    usage in systemd services.
    
    Args:
        service_name: Name of the service (e.g., "dnsmasq-homelab.service")
        action: Action to perform ("start", "stop", "restart", "reload")
        
    Raises:
        subprocess.CalledProcessError: If the command fails
    """
    # Validate action
    valid_actions = ['start', 'stop', 'restart', 'reload']
    if action.lower() not in valid_actions:
        logger.error(f"Invalid action: {action}")
        raise ValueError(f"Invalid action: {action}. Must be one of: {valid_actions}")
    
    socket_path = "/run/router-webui/service-control.sock"
    
    # Send command to socket (format: "ACTION SERVICE\n")
    try:
        import socket
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(socket_path)
        command = f"{action.lower()} {service_name}\n"
        sock.sendall(command.encode('utf-8'))
        sock.shutdown(socket.SHUT_WR)
        
        # Read response
        response = b""
        while True:
            data = sock.recv(4096)
            if not data:
                break
            response += data
        
        sock.close()
        
        # Check if there was an error in the response
        response_str = response.decode('utf-8', errors='ignore')
        if "Invalid" in response_str or "Failed" in response_str or "error" in response_str.lower():
            logger.error(f"Service control returned error: {response_str}")
            raise subprocess.CalledProcessError(1, f"service control command", stderr=response_str)
        
        logger.debug(f"Service control command '{command}' completed successfully: {response_str}")
        
    except (socket.error, OSError) as e:
        logger.error(f"Failed to communicate with service control socket: {e}")
        raise subprocess.CalledProcessError(1, f"service control command", stderr=str(e))

router = APIRouter(prefix="/api/blocklists", tags=["blocklists"])


@router.get("/{network}", response_model=BlocklistsConfig)
async def get_blocklists(
    network: str,
    current_user: str = Depends(get_current_user)
):
    """Get blocklists configuration for a network"""
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Invalid network. Must be 'homelab' or 'lan'")
    
    try:
        config = parse_blocklists_nix_file(network)
        if config is None:
            # Return default config if file doesn't exist
            config = {
                'enable': True,
                'blocklists': {}
            }
        return BlocklistsConfig(**config)
    except Exception as e:
        logger.error(f"Error reading blocklists config for {network}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read blocklists configuration: {str(e)}")


@router.put("/{network}", response_model=BlocklistsConfig)
async def update_blocklists(
    network: str,
    config_update: BlocklistsConfigUpdate,
    current_user: str = Depends(get_current_user)
):
    """Update blocklists configuration for a network"""
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Invalid network. Must be 'homelab' or 'lan'")
    
    try:
        # Read current config
        current = parse_blocklists_nix_file(network)
        if current is None:
            current = {
                'enable': True,
                'blocklists': {}
            }
        
        # Apply updates
        updated_config = {**current}
        if config_update.enable is not None:
            updated_config['enable'] = config_update.enable
        if config_update.blocklists is not None:
            # Merge blocklist updates
            updated_blocklists = {**updated_config.get('blocklists', {})}
            for blocklist_name, blocklist_update in config_update.blocklists.items():
                if blocklist_name in updated_blocklists:
                    updated_blocklists[blocklist_name] = {**updated_blocklists[blocklist_name], **blocklist_update.dict(exclude_unset=True)}
                else:
                    updated_blocklists[blocklist_name] = blocklist_update.dict()
            updated_config['blocklists'] = updated_blocklists
        
        # Format as Nix
        nix_content = write_blocklists_nix_file(
            network=network,
            enable=updated_config['enable'],
            blocklists=updated_config.get('blocklists', {})
        )
        
        # Write via socket service
        write_blocklists_nix_config(network, nix_content)
        
        # Restart dnsmasq service to pick up blocklist changes
        service_name = f"{NETWORK_SERVICE_MAP[network]}.service"
        try:
            _control_service_via_systemctl(service_name, "restart")
            logger.info(f"Blocklists config written and dnsmasq service restarted for network {network}")
        except Exception as restart_error:
            logger.error(f"Failed to restart {service_name}: {restart_error}")
            # Don't raise - allow the API call to succeed even if service control fails
        
        logger.info(f"Blocklists configuration for {network} updated by {current_user}")
        return BlocklistsConfig(**updated_config)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating blocklists config for {network}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update blocklists configuration: {str(e)}")

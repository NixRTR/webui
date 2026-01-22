"""
Client for communicating with router-webui-config-writer socket-activated service
"""
import logging
import socket
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)

SOCKET_PATH = "/run/router-webui/config-writer.sock"


def write_dns_config(network: str, config_content: str) -> None:
    """Write DNS configuration file via socket-activated helper service
    
    Args:
        network: Network name ("homelab" or "lan")
        config_content: DNS configuration content to write
        
    Raises:
        subprocess.CalledProcessError: If the command fails
        ValueError: If network is invalid
    """
    if network not in ['homelab', 'lan']:
        raise ValueError(f"Invalid network: {network}. Must be 'homelab' or 'lan'")
    
    _send_command(f"write-dns {network}", config_content)


def write_dhcp_config(network: str, config_content: str) -> None:
    """Write DHCP configuration file via socket-activated helper service
    
    Args:
        network: Network name ("homelab" or "lan")
        config_content: DHCP configuration content to write (can be None to delete)
        
    Raises:
        subprocess.CalledProcessError: If the command fails
        ValueError: If network is invalid
    """
    if network not in ['homelab', 'lan']:
        raise ValueError(f"Invalid network: {network}. Must be 'homelab' or 'lan'")
    
    _send_command(f"write-dhcp {network}", config_content)


def revert_dns_config(network: str, history_id: int, config_content: str) -> None:
    """Revert DNS configuration to a previous state
    
    Args:
        network: Network name ("homelab" or "lan")
        history_id: History record ID to revert to
        config_content: DNS configuration content from history
        
    Raises:
        subprocess.CalledProcessError: If the command fails
        ValueError: If network is invalid
    """
    if network not in ['homelab', 'lan']:
        raise ValueError(f"Invalid network: {network}. Must be 'homelab' or 'lan'")
    
    _send_command(f"revert-dns {network} {history_id}", config_content)


def revert_dhcp_config(network: str, history_id: int, config_content: str) -> None:
    """Revert DHCP configuration to a previous state
    
    Args:
        network: Network name ("homelab" or "lan")
        history_id: History record ID to revert to
        config_content: DHCP configuration content from history
        
    Raises:
        subprocess.CalledProcessError: If the command fails
        ValueError: If network is invalid
    """
    if network not in ['homelab', 'lan']:
        raise ValueError(f"Invalid network: {network}. Must be 'homelab' or 'lan'")
    
    _send_command(f"revert-dhcp {network} {history_id}", config_content)


def _send_command(command: str, content: Optional[str]) -> None:
    """Send command and content to config writer socket
    
    Args:
        command: Command string (e.g., "write-dns homelab")
        content: Configuration content to write (can be None)
        
    Raises:
        subprocess.CalledProcessError: If the command fails
    """
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(30)
        sock.connect(SOCKET_PATH)
        
        # Send command line
        sock.sendall(f"{command}\n".encode('utf-8'))
        
        # Send content (if provided)
        if content is not None:
            sock.sendall(content.encode('utf-8'))
        
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
            logger.error(f"Config writer returned error: {response_str}")
            raise subprocess.CalledProcessError(1, f"config writer command", stderr=response_str)
        
        logger.debug(f"Config writer command '{command}' completed successfully")
        
    except (socket.error, OSError) as e:
        logger.error(f"Failed to communicate with config writer socket: {e}")
        raise subprocess.CalledProcessError(1, f"config writer command", stderr=str(e))

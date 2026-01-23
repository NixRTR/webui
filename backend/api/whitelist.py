"""
DNS Whitelist configuration API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import logging

from ..api.auth import get_current_user
from ..models import WhitelistConfig, WhitelistConfigUpdate
from ..utils.whitelist_parser import parse_whitelist_nix_file
from ..utils.nix_writer import write_whitelist_nix_file
from ..utils.config_writer import write_whitelist_nix_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/whitelist", tags=["whitelist"])


@router.get("/{network}", response_model=WhitelistConfig)
async def get_whitelist(
    network: str,
    current_user: str = Depends(get_current_user)
):
    """Get whitelist configuration for a network"""
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Invalid network. Must be 'homelab' or 'lan'")
    
    try:
        domains = parse_whitelist_nix_file(network)
        if domains is None:
            domains = []
        return WhitelistConfig(domains=domains)
    except Exception as e:
        logger.error(f"Error reading whitelist config for {network}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read whitelist configuration: {str(e)}")


@router.put("/{network}", response_model=WhitelistConfig)
async def update_whitelist(
    network: str,
    config_update: WhitelistConfigUpdate,
    current_user: str = Depends(get_current_user)
):
    """Update whitelist configuration for a network"""
    if network not in ['homelab', 'lan']:
        raise HTTPException(status_code=400, detail="Invalid network. Must be 'homelab' or 'lan'")
    
    try:
        # Read current config
        current_domains = parse_whitelist_nix_file(network)
        if current_domains is None:
            current_domains = []
        
        # Apply updates
        if config_update.domains is not None:
            updated_domains = config_update.domains
        else:
            updated_domains = current_domains
        
        # Format as Nix
        nix_content = write_whitelist_nix_file(
            network=network,
            domains=updated_domains
        )
        
        # Write via socket service
        write_whitelist_nix_config(network, nix_content)
        
        logger.info(f"Whitelist configuration for {network} updated by {current_user}")
        return WhitelistConfig(domains=updated_domains)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating whitelist config for {network}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update whitelist configuration: {str(e)}")

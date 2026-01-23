"""
DNS Blocklists configuration API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import logging

from ..api.auth import get_current_user
from ..models import BlocklistsConfig, BlocklistsConfigUpdate
from ..utils.blocklists_parser import parse_blocklists_nix_file
from ..utils.nix_writer import write_blocklists_nix_file
from ..utils.config_writer import write_blocklists_nix_config

logger = logging.getLogger(__name__)

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
        
        logger.info(f"Blocklists configuration for {network} updated by {current_user}")
        return BlocklistsConfig(**updated_config)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating blocklists config for {network}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update blocklists configuration: {str(e)}")

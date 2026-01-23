"""
CAKE configuration API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import logging

from ..api.auth import get_current_user
from ..models import CakeConfig, CakeConfigUpdate
from ..utils.cake_parser import parse_cake_nix_file
from ..utils.nix_writer import write_cake_nix_file
from ..utils.config_writer import write_cake_nix_config
from ..config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/cake", tags=["cake-config"])


@router.get("/config", response_model=CakeConfig)
async def get_cake_config(current_user: str = Depends(get_current_user)):
    """Get CAKE traffic shaping configuration"""
    try:
        config = parse_cake_nix_file()
        if config is None:
            # Return default config if file doesn't exist
            config = {
                'enable': False,
                'aggressiveness': 'auto',
                'uploadBandwidth': None,
                'downloadBandwidth': None
            }
        return CakeConfig(**config)
    except Exception as e:
        logger.error(f"Error reading CAKE config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read CAKE configuration: {str(e)}")


@router.put("/config", response_model=CakeConfig)
async def update_cake_config(
    config_update: CakeConfigUpdate,
    current_user: str = Depends(get_current_user)
):
    """Update CAKE traffic shaping configuration"""
    try:
        # Read current config
        current = parse_cake_nix_file()
        if current is None:
            current = {
                'enable': False,
                'aggressiveness': 'auto',
                'uploadBandwidth': None,
                'downloadBandwidth': None
            }
        
        # Apply updates
        updated_config = {**current}
        if config_update.enable is not None:
            updated_config['enable'] = config_update.enable
        if config_update.aggressiveness is not None:
            updated_config['aggressiveness'] = config_update.aggressiveness
        if config_update.uploadBandwidth is not None:
            updated_config['uploadBandwidth'] = config_update.uploadBandwidth
        if config_update.downloadBandwidth is not None:
            updated_config['downloadBandwidth'] = config_update.downloadBandwidth
        
        # Format as Nix
        nix_content = write_cake_nix_file(
            enable=updated_config['enable'],
            aggressiveness=updated_config['aggressiveness'],
            uploadBandwidth=updated_config.get('uploadBandwidth'),
            downloadBandwidth=updated_config.get('downloadBandwidth')
        )
        
        # Write via socket service
        write_cake_nix_config(nix_content)
        
        logger.info(f"CAKE configuration updated by {current_user}")
        return CakeConfig(**updated_config)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating CAKE config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update CAKE configuration: {str(e)}")

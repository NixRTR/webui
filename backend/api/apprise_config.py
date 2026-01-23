"""
Apprise configuration API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Dict, Any
import logging

from ..api.auth import get_current_user
from ..models import AppriseConfig, AppriseConfigUpdate, AppriseServiceConfig
from ..utils.apprise_parser import parse_apprise_nix_file
from ..utils.nix_writer import write_apprise_nix_file
from ..utils.config_writer import write_apprise_nix_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/apprise", tags=["apprise-config"])


@router.get("/config", response_model=AppriseConfig)
async def get_apprise_config(current_user: str = Depends(get_current_user)):
    """Get Apprise API configuration"""
    try:
        config = parse_apprise_nix_file()
        if config is None:
            # Return default config if file doesn't exist
            config = {
                'enable': True,
                'port': 8001,
                'attachSize': 0,
                'services': {}
            }
        return AppriseConfig(**config)
    except Exception as e:
        logger.error(f"Error reading Apprise config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read Apprise configuration: {str(e)}")


@router.put("/config", response_model=AppriseConfig)
async def update_apprise_config(
    config_update: AppriseConfigUpdate,
    current_user: str = Depends(get_current_user)
):
    """Update Apprise API configuration"""
    try:
        # Read current config
        current = parse_apprise_nix_file()
        if current is None:
            current = {
                'enable': True,
                'port': 8001,
                'attachSize': 0,
                'services': {}
            }
        
        # Apply updates
        updated_config = {**current}
        if config_update.enable is not None:
            updated_config['enable'] = config_update.enable
        if config_update.port is not None:
            updated_config['port'] = config_update.port
        if config_update.attachSize is not None:
            updated_config['attachSize'] = config_update.attachSize
        if config_update.services is not None:
            # Merge service updates with existing services
            updated_services = {**updated_config.get('services', {})}
            for service_name, service_update in config_update.services.items():
                if service_name in updated_services:
                    updated_services[service_name] = {**updated_services[service_name], **service_update.dict(exclude_unset=True)}
                else:
                    updated_services[service_name] = service_update.dict()
            updated_config['services'] = updated_services
        
        # Format as Nix
        nix_content = write_apprise_nix_file(
            enable=updated_config['enable'],
            port=updated_config['port'],
            attachSize=updated_config['attachSize'],
            services=updated_config.get('services', {})
        )
        
        # Write via socket service
        write_apprise_nix_config(nix_content)
        
        logger.info(f"Apprise configuration updated by {current_user}")
        return AppriseConfig(**updated_config)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating Apprise config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update Apprise configuration: {str(e)}")

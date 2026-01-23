"""
Dynamic DNS configuration API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import logging

from ..api.auth import get_current_user
from ..models import DynDnsConfig, DynDnsConfigUpdate
from ..utils.dyndns_parser import parse_dyndns_nix_file
from ..utils.nix_writer import write_dyndns_nix_file
from ..utils.config_writer import write_dyndns_nix_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dyndns", tags=["dyndns-config"])


@router.get("/config", response_model=DynDnsConfig)
async def get_dyndns_config(current_user: str = Depends(get_current_user)):
    """Get Dynamic DNS configuration"""
    try:
        config = parse_dyndns_nix_file()
        if config is None:
            # Return default config if file doesn't exist
            config = {
                'enable': True,
                'provider': 'linode',
                'domain': '',
                'subdomain': '',
                'domainId': 0,
                'recordId': 0,
                'checkInterval': '5m'
            }
        return DynDnsConfig(**config)
    except Exception as e:
        logger.error(f"Error reading Dynamic DNS config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read Dynamic DNS configuration: {str(e)}")


@router.put("/config", response_model=DynDnsConfig)
async def update_dyndns_config(
    config_update: DynDnsConfigUpdate,
    current_user: str = Depends(get_current_user)
):
    """Update Dynamic DNS configuration"""
    try:
        # Read current config
        current = parse_dyndns_nix_file()
        if current is None:
            current = {
                'enable': True,
                'provider': 'linode',
                'domain': '',
                'subdomain': '',
                'domainId': 0,
                'recordId': 0,
                'checkInterval': '5m'
            }
        
        # Apply updates
        updated_config = {**current}
        if config_update.enable is not None:
            updated_config['enable'] = config_update.enable
        if config_update.provider is not None:
            updated_config['provider'] = config_update.provider
        if config_update.domain is not None:
            updated_config['domain'] = config_update.domain
        if config_update.subdomain is not None:
            updated_config['subdomain'] = config_update.subdomain
        if config_update.domainId is not None:
            updated_config['domainId'] = config_update.domainId
        if config_update.recordId is not None:
            updated_config['recordId'] = config_update.recordId
        if config_update.checkInterval is not None:
            updated_config['checkInterval'] = config_update.checkInterval
        
        # Format as Nix
        nix_content = write_dyndns_nix_file(
            enable=updated_config['enable'],
            provider=updated_config['provider'],
            domain=updated_config['domain'],
            subdomain=updated_config['subdomain'],
            domainId=updated_config['domainId'],
            recordId=updated_config['recordId'],
            checkInterval=updated_config['checkInterval']
        )
        
        # Write via socket service
        write_dyndns_nix_config(nix_content)
        
        logger.info(f"Dynamic DNS configuration updated by {current_user}")
        return DynDnsConfig(**updated_config)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating Dynamic DNS config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update Dynamic DNS configuration: {str(e)}")

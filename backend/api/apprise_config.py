"""
Apprise configuration API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Dict, Any
import logging
from pydantic import BaseModel

from ..api.auth import get_current_user
from ..models import AppriseConfig, AppriseConfigUpdate, AppriseServiceConfig
from ..utils.apprise_parser import parse_apprise_nix_file
from ..utils.nix_writer import write_apprise_nix_file
from ..utils.config_writer import write_apprise_nix_config
from ..utils.apprise import test_service, is_apprise_enabled, _load_apprise_config_from_file, url_encode_password_in_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/apprise", tags=["apprise-config"])


class NotificationResponse(BaseModel):
    """Response model for notification requests"""
    success: bool
    message: str
    details: Optional[str] = None


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


def _get_service_url_by_name(service_name: str) -> Optional[str]:
    """Get Apprise service URL by service name from apprise config file
    
    Args:
        service_name: Service name (e.g., "email", "homeAssistant", "discord", etc.)
        
    Returns:
        Service URL if found, None otherwise
    """
    try:
        import os
        from ..utils.apprise import DEFAULT_APPRISE_CONFIG
        
        # Read the apprise config file directly
        config_path = os.getenv('APPRISE_CONFIG_FILE', DEFAULT_APPRISE_CONFIG)
        if not os.path.exists(config_path):
            logger.warning(f"Apprise config file not found: {config_path}")
            return None
        
        service_name_lower = service_name.lower()
        
        with open(config_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Config file format: description|url or just url
                if '|' in line:
                    parts = line.split('|', 1)
                    description = parts[0].lower()
                    url = parts[1]
                else:
                    url = line
                    description = ''
                
                # Match by description or URL pattern
                if service_name_lower in description:
                    return url
                
                # Match by URL scheme/pattern
                url_lower = url.lower()
                if service_name_lower == 'email' and ('mailto://' in url_lower or 'mailtos://' in url_lower):
                    return url
                elif service_name_lower == 'homeassistant' and ('hass://' in url_lower or 'hasss://' in url_lower):
                    return url
                elif service_name_lower == 'discord' and 'discord://' in url_lower:
                    return url
                elif service_name_lower == 'slack' and 'slack://' in url_lower:
                    return url
                elif service_name_lower == 'telegram' and ('tgram://' in url_lower or 'telegram://' in url_lower):
                    return url
                elif service_name_lower == 'ntfy' and 'ntfy://' in url_lower:
                    return url
        
        return None
    except Exception as e:
        logger.error(f"Error getting service URL for {service_name}: {e}", exc_info=True)
        return None


@router.post("/config/test/{service_name}", response_model=NotificationResponse)
async def test_service_by_name(
    service_name: str,
    current_user: str = Depends(get_current_user)
):
    """Test a specific notification service by name
    
    Args:
        service_name: Service name (e.g., "email", "homeAssistant", "discord", etc.)
        
    Returns:
        NotificationResponse: Success status and message
    """
    try:
        if not is_apprise_enabled():
            raise HTTPException(
                status_code=503,
                detail="Apprise is not enabled"
            )
        
        # Get service URL
        service_url = _get_service_url_by_name(service_name)
        if not service_url:
            raise HTTPException(
                status_code=404,
                detail=f"Service '{service_name}' not found or not configured"
            )
        
        # Check if service is enabled in Nix config
        config = parse_apprise_nix_file()
        if config and config.get('services', {}).get(service_name, {}).get('enable') != True:
            raise HTTPException(
                status_code=400,
                detail=f"Service '{service_name}' is not enabled"
            )
        
        # Send test message
        test_message = f"Test Message for NixOS-Router via {service_name}"
        success, error, details = test_service(
            service_url,
            body=test_message,
            title="NixOS Router Test",
            notification_type="info"
        )
        
        if success:
            return NotificationResponse(
                success=True,
                message=f"Test notification sent successfully to {service_name}",
                details=details
            )
        else:
            return NotificationResponse(
                success=False,
                message=error or f"Failed to send test notification to {service_name}",
                details=details
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing service {service_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to test service: {str(e)}")


@router.post("/config/test-all", response_model=NotificationResponse)
async def test_all_services(
    current_user: str = Depends(get_current_user)
):
    """Test all enabled notification services
    
    Returns:
        NotificationResponse: Success status and message
    """
    try:
        if not is_apprise_enabled():
            raise HTTPException(
                status_code=503,
                detail="Apprise is not enabled"
            )
        
        # Get all enabled services from Nix config
        config = parse_apprise_nix_file()
        if not config:
            raise HTTPException(
                status_code=404,
                detail="Apprise configuration not found"
            )
        
        services = config.get('services', {})
        enabled_services = {name: svc for name, svc in services.items() if svc.get('enable') == True}
        
        if not enabled_services:
            raise HTTPException(
                status_code=400,
                detail="No enabled services found"
            )
        
        # Build Apprise object with all enabled service URLs
        from apprise import Apprise
        
        # Load Apprise config from file
        apobj = _load_apprise_config_from_file()
        if not apobj or len(apobj) == 0:
            raise HTTPException(
                status_code=404,
                detail="No service URLs found in Apprise configuration"
            )
        
        test_message = "Test Message for ALL NixOS-Router services"
        
        # Send notification to all services
        result = apobj.notify(
            body=test_message,
            title="NixOS Router Test",
            notify_type="info"
        )
        
        if result:
            return NotificationResponse(
                success=True,
                message=f"Test notification sent successfully to all enabled services",
                details=None
            )
        else:
            return NotificationResponse(
                success=False,
                message="Failed to send test notification to all services",
                details=None
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error testing all services: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to test all services: {str(e)}")

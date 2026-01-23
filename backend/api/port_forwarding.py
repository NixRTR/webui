"""
Port Forwarding configuration API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
import logging

from ..api.auth import get_current_user
from ..models import PortForwardingRule, PortForwardingRuleCreate, PortForwardingRuleUpdate
from ..utils.port_forwarding_parser import parse_port_forwarding_nix_file
from ..utils.nix_writer import write_port_forwarding_nix_file
from ..utils.config_writer import write_port_forwarding_nix_config
from ..utils.port_forwarding_applier import apply_port_forwarding_rules

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/port-forwarding", tags=["port-forwarding"])


@router.get("", response_model=List[PortForwardingRule])
async def get_port_forwarding_rules(current_user: str = Depends(get_current_user)):
    """Get all port forwarding rules"""
    try:
        rules = parse_port_forwarding_nix_file()
        if rules is None:
            rules = []
        
        # Add index to each rule
        return [PortForwardingRule(index=i, **rule) for i, rule in enumerate(rules)]
    except Exception as e:
        logger.error(f"Error reading port forwarding rules: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to read port forwarding rules: {str(e)}")


@router.post("", response_model=PortForwardingRule)
async def create_port_forwarding_rule(
    rule: PortForwardingRuleCreate,
    current_user: str = Depends(get_current_user)
):
    """Add a new port forwarding rule"""
    try:
        # Read current rules
        rules = parse_port_forwarding_nix_file()
        if rules is None:
            rules = []
        
        # Add new rule
        new_rule = rule.dict()
        rules.append(new_rule)
        
        # Format as Nix
        nix_content = write_port_forwarding_nix_file(rules)
        
        # Write via socket service (this will also apply iptables rules)
        write_port_forwarding_nix_config(nix_content)
        
        # Apply iptables rules immediately (also done in config writer, but do it here as backup)
        try:
            apply_port_forwarding_rules()
            logger.info("Port forwarding rules applied to iptables")
        except Exception as apply_error:
            logger.warning(f"Failed to apply port forwarding rules (config writer should have done this): {apply_error}")
            # Don't fail the API call if rule application fails
        
        logger.info(f"Port forwarding rule added by {current_user}")
        return PortForwardingRule(index=len(rules) - 1, **new_rule)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding port forwarding rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to add port forwarding rule: {str(e)}")


@router.put("/{index}", response_model=PortForwardingRule)
async def update_port_forwarding_rule(
    index: int,
    rule_update: PortForwardingRuleUpdate,
    current_user: str = Depends(get_current_user)
):
    """Update a port forwarding rule by index"""
    try:
        # Read current rules
        rules = parse_port_forwarding_nix_file()
        if rules is None:
            rules = []
        
        if index < 0 or index >= len(rules):
            raise HTTPException(status_code=404, detail=f"Port forwarding rule at index {index} not found")
        
        # Apply updates
        updated_rule = {**rules[index]}
        update_dict = rule_update.dict(exclude_unset=True)
        updated_rule.update(update_dict)
        rules[index] = updated_rule
        
        # Format as Nix
        nix_content = write_port_forwarding_nix_file(rules)
        
        # Write via socket service (this will also apply iptables rules)
        write_port_forwarding_nix_config(nix_content)
        
        # Apply iptables rules immediately (also done in config writer, but do it here as backup)
        try:
            apply_port_forwarding_rules()
            logger.info("Port forwarding rules applied to iptables")
        except Exception as apply_error:
            logger.warning(f"Failed to apply port forwarding rules (config writer should have done this): {apply_error}")
            # Don't fail the API call if rule application fails
        
        logger.info(f"Port forwarding rule {index} updated by {current_user}")
        return PortForwardingRule(index=index, **updated_rule)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating port forwarding rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to update port forwarding rule: {str(e)}")


@router.delete("/{index}")
async def delete_port_forwarding_rule(
    index: int,
    current_user: str = Depends(get_current_user)
):
    """Delete a port forwarding rule by index"""
    try:
        # Read current rules
        rules = parse_port_forwarding_nix_file()
        if rules is None:
            rules = []
        
        if index < 0 or index >= len(rules):
            raise HTTPException(status_code=404, detail=f"Port forwarding rule at index {index} not found")
        
        # Remove rule
        rules.pop(index)
        
        # Format as Nix
        nix_content = write_port_forwarding_nix_file(rules)
        
        # Write via socket service (this will also apply iptables rules)
        write_port_forwarding_nix_config(nix_content)
        
        # Apply iptables rules immediately (also done in config writer, but do it here as backup)
        try:
            apply_port_forwarding_rules()
            logger.info("Port forwarding rules applied to iptables")
        except Exception as apply_error:
            logger.warning(f"Failed to apply port forwarding rules (config writer should have done this): {apply_error}")
            # Don't fail the API call if rule application fails
        
        logger.info(f"Port forwarding rule {index} deleted by {current_user}")
        return {"message": "Port forwarding rule deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting port forwarding rule: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete port forwarding rule: {str(e)}")

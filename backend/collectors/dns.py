"""
DNS statistics collector (deprecated - dnsmasq doesn't provide control socket)
"""
from datetime import datetime, timezone
from typing import List, Optional
from ..models import DNSMetrics


def get_unbound_stats(instance: str) -> Optional[DNSMetrics]:
    """Get statistics from DNS server (deprecated - dnsmasq doesn't provide control socket)
    
    Args:
        instance: 'homelab' or 'lan'
        
    Returns:
        None - dnsmasq doesn't provide real-time statistics like Unbound's control socket
    """
    # dnsmasq doesn't have a control socket like Unbound
    # Statistics would require parsing syslog after sending SIGUSR1 signal
    # For now, return None to disable DNS statistics collection
    return None


def collect_dns_stats() -> List[DNSMetrics]:
    """Collect DNS statistics for all instances
    
    Returns:
        List[DNSMetrics]: Empty list - dnsmasq doesn't provide statistics via control socket
    """
    # dnsmasq doesn't provide statistics collection like Unbound
    # Return empty list to maintain API compatibility
    return []


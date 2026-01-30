"""
Application configuration using Pydantic Settings
"""
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings"""
    
    # Application
    app_name: str = "Router WebUI"
    debug: bool = False
    
    # Server
    host: str = "0.0.0.0"
    port: int = 8080
    
    # Database
    database_url: str = "postgresql+asyncpg://router_webui:password@localhost/router_webui"
    
    # JWT Authentication
    jwt_secret_key: str = "change-this-in-production"
    jwt_secret_file: Optional[str] = None  # Path to JWT secret file
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 60 * 24  # 24 hours
    
    # Data Collection
    collection_interval: int = 5  # seconds (increased from 2 to reduce DB writes)
    collection_interval_normal: int = 5  # Normal collection interval (seconds)
    collection_interval_throttled: int = 10  # Throttled collection interval (seconds)
    
    # Client Bandwidth Tracking
    bandwidth_collection_enabled: bool = True
    bandwidth_max_cpu_percent: float = 80.0  # Skip collection if CPU > this threshold
    bandwidth_max_clients_per_cycle: int = 50  # Process max N clients per cycle
    bandwidth_collection_priority: int = 10  # Nice value (lower priority)
    
    # System Paths
    dnsmasq_lease_files: str = "/var/lib/dnsmasq/homelab/dhcp.leases /var/lib/dnsmasq/lan/dhcp.leases"
    router_config_file: str = "/etc/nixos/router-config.nix"
    dnsmasq_config_dir: str = "/etc/nixos/config/dnsmasq"
    dns_homelab_file: str = "/etc/nixos/config/dnsmasq/dns-homelab.nix"
    dns_lan_file: str = "/etc/nixos/config/dnsmasq/dns-lan.nix"
    dhcp_homelab_file: str = "/etc/nixos/config/dnsmasq/dhcp-homelab.nix"
    dhcp_lan_file: str = "/etc/nixos/config/dnsmasq/dhcp-lan.nix"
    dhcp_reservations_homelab_file: str = "/etc/nixos/config/dnsmasq/dhcp-reservations-homelab.nix"
    dhcp_reservations_lan_file: str = "/etc/nixos/config/dnsmasq/dhcp-reservations-lan.nix"
    cake_config_file: str = "/etc/nixos/config/cake.nix"
    apprise_config_file: str = "/etc/nixos/config/apprise.nix"
    dyndns_config_file: str = "/etc/nixos/config/dyndns.nix"
    port_forwarding_config_file: str = "/etc/nixos/config/port-forwarding.nix"
    blocklists_homelab_file: str = "/etc/nixos/config/dnsmasq/blocklists-homelab.nix"
    blocklists_lan_file: str = "/etc/nixos/config/dnsmasq/blocklists-lan.nix"
    whitelist_homelab_file: str = "/etc/nixos/config/dnsmasq/whitelist-homelab.nix"
    whitelist_lan_file: str = "/etc/nixos/config/dnsmasq/whitelist-lan.nix"
    
    # Historical Data Retention
    metrics_retention_days: int = 30
    
    # Notifications
    notification_check_interval: int = 30  # seconds between evaluation cycles
    
    # Multi-Factor Throttling Configuration
    max_pending_write_tasks: int = 5  # Max pending DB write operations before throttling
    max_db_write_latency_ms: float = 500.0  # Max DB write time in milliseconds before throttling
    max_io_wait_percent: float = 20.0  # Max I/O wait percentage before throttling
    max_loadavg_1m: float = 3.0  # Fallback: max 1-minute loadavg before throttling
    max_loadavg_5m: float = 2.0  # Fallback: max 5-minute loadavg before throttling
    bandwidth_collection_enabled_under_load: bool = False  # Disable bandwidth collection under high load
    
    # CORS (for development - production serves from same origin via nginx)
    # In production, nginx serves everything from the same origin, so CORS is not needed
    # For development, allow localhost origins
    cors_origins: list = ["http://localhost:3000", "http://localhost:5173", "http://localhost:8080"]
    
    # Redis Configuration
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    redis_write_buffer_enabled: bool = True
    redis_buffer_flush_interval: int = 5  # seconds
    redis_buffer_max_size: int = 100  # items per buffer
    redis_cache_ttl_rules: int = 60  # seconds
    redis_cache_ttl_overrides: int = 30  # seconds
    redis_cache_ttl_api: int = 10  # seconds

    # Worker Status (Celery) - threshold in seconds for "long-running" tasks
    worker_status_long_running_seconds: int = 300

    class Config:
        env_file = "/etc/router-webui/config.env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# Helper function to load JWT secret from file
def load_jwt_secret(settings_obj: Settings) -> str:
    """Load JWT secret from file if specified, otherwise use default"""
    if settings_obj.jwt_secret_file and os.path.exists(settings_obj.jwt_secret_file):
        try:
            with open(settings_obj.jwt_secret_file, 'r') as f:
                secret = f.read().strip()
                if secret:
                    return secret
        except Exception as e:
            print(f"Warning: Could not read JWT secret from {settings_obj.jwt_secret_file}: {e}")
    
    return settings_obj.jwt_secret_key


# Global settings instance
settings = Settings()

# Load JWT secret from file if available
settings.jwt_secret_key = load_jwt_secret(settings)


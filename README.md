# Router WebUI

A modern web-based monitoring and management interface for the NixOS router, built with FastAPI (backend) and React + Flowbite (frontend).

## Architecture

### Backend (FastAPI + PostgreSQL)
- **FastAPI** - Modern async Python web framework
- **PostgreSQL** - Time-series data storage for metrics and configuration (DNS, DHCP, Apprise, notifications)
- **WebSockets** - Real-time metrics broadcasting
- **JWT Authentication** - System user authentication via PAM
- **SQLAlchemy** - Async ORM for database operations

### Celery + Redis
- **Celery** - Background task queue (workers + beat scheduler)
- **Redis** - Message broker and buffer/cache for Celery; also used for API response caching
- Background tasks (aggregation, notifications, port scanner, history cleanup) run in Celery processes, not in the FastAPI process. Production deploys use separate `router-webui-celery-worker` and `router-webui-celery-beat` services.

### Frontend (React + TypeScript)
- **React 18** - Modern UI library
- **TypeScript** - Type-safe development
- **Flowbite React** - Tailwind CSS component library
- **Recharts** - Beautiful, responsive charts
- **Vite** - Fast build tooling

### Data Collection
- **psutil** - System metrics (CPU, memory, load, uptime)
- **dnsmasq DHCP** - Parse lease files for client information
- **dnsmasq DNS** - DNS statistics collection (where supported)
- **Systemd** - Service status monitoring
- **Network interfaces** - Real-time bandwidth monitoring

## Features

**Real-time monitoring**
- Dashboard with system metrics (CPU, memory, load average, uptime)
- Network interface statistics with live bandwidth graphs
- Per-device bandwidth and usage tracking
- Service status monitoring (DNS/DHCP, PPPoE, etc.)
- Speedtest with historical results

**Configuration management**
- **DHCP** - Configure DHCP networks and static reservations per network (homelab/lan)
- **DNS** - Configure DNS zones and records per network
- **CAKE** - View and configure CAKE traffic shaping
- **Apprise** - Manage notification services (email, Discord, Telegram, etc.)
- **Dynamic DNS** - Configure DynDns providers and updates
- **Port Forwarding** - Manage port forwarding rules
- **Blocklists and Whitelist** - Manage blocklists and whitelist per network

**Other**
- **Notifications** - Automated alert rules based on system metrics; send test notifications via Apprise
- **Service control** - Start, stop, restart, reload DNS and DHCP services from the WebUI
- **Worker Status** - View Celery worker and task status
- **Logs** - System and application logs
- **Documentation** - In-app link to the project documentation site

**Authentication and UX**
- System user login (PAM), JWT token-based sessions
- Responsive design, dark mode, mobile-friendly
- In-app Documentation link

## Development Setup

### Backend Development

```bash
cd webui/backend

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export DATABASE_URL="postgresql+asyncpg://router_webui:password@localhost/router_webui"
export JWT_SECRET_KEY="your-secret-key-here"
export DEBUG=true

# Run development server
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8080

# Access API docs
open http://localhost:8080/docs
```

For full configuration management and background tasks, Redis (and optionally Celery worker/beat) must be running; see Configuration below. Production on NixOS runs Celery as separate systemd services.

### Frontend Development

```bash
cd webui/frontend

# Install dependencies
npm install

# Run development server (with proxy to backend)
npm run dev

# Access frontend
open http://localhost:3000
```

### Database Setup (Development)

```bash
# Create PostgreSQL database
createdb router_webui

# Run schema and migrations (see backend/migrations/)
psql router_webui < webui/backend/schema.sql
# Then apply migrations in backend/migrations/ as needed
```

## Production Deployment (NixOS)

### 1. Enable in `configuration.nix`

```nix
{
  imports = [
    # ... other modules
    ./modules/webui.nix
  ];

  services.router-webui = {
    enable = true;
    port = 8080;
    collectionInterval = 2;  # seconds
  };

  # Open firewall for WebUI
  networking.firewall.allowedTCPPorts = [ 8080 ];
}
```

### 2. Build Frontend

```bash
cd webui/frontend
npm install
npm run build
```

### 3. Deploy

```bash
sudo nixos-rebuild switch
```

### 4. Access

Open `http://router-ip:8080` in your browser

**Default credentials:** Your system user account

## API Endpoints

### Authentication
- `POST /api/auth/login` - Login with system credentials
- `GET /api/auth/me` - Get current user info
- `POST /api/auth/logout` - Logout

### Real-time Data
- `WS /ws?token={jwt}` - WebSocket for real-time metrics

### Historical Data
- `GET /api/history/system` - System metrics history
- `GET /api/history/interface/{name}` - Interface statistics history
- `GET /api/history/bandwidth/{network}?period={1h|24h|7d|30d}` - Bandwidth history
- `GET /api/history/services` - Service status history

### Monitoring and Devices
- `GET /api/bandwidth/*` - Bandwidth and connection history
- `GET /api/devices/*` - Devices and client data
- `GET /api/system/*` - System metrics and info
- `GET /api/speedtest/*` - Speedtest results and history
- `GET /api/cake/*` - CAKE status and configuration (read/write)

### Configuration
- `GET/POST /api/dns/*` - DNS zones and records
- `GET/POST /api/dhcp/*` - DHCP networks and reservations
- `GET/POST /api/apprise/*` - Apprise services and send test
- `GET/POST /api/dyndns/*` - Dynamic DNS configuration
- `GET/POST /api/port-forwarding/*` - Port forwarding rules
- `GET /api/blocklists/*` - Blocklists configuration
- `GET /api/whitelist/*` - Whitelist configuration

### Notifications and Workers
- `GET/POST /api/notifications/*` - Notification rules
- `GET /api/worker-status/*` - Celery worker and task status
- `GET /api/logs/*` - System/application logs

### Health Check
- `GET /api/health` - Service health status

## WebSocket Message Format

```json
{
  "type": "metrics",
  "data": {
    "timestamp": "2024-01-01T00:00:00",
    "system": {
      "cpu_percent": 25.5,
      "memory_percent": 45.2,
      "load_avg_1m": 0.85,
      ...
    },
    "interfaces": [
      {
        "interface": "ppp0",
        "rx_rate_mbps": 15.2,
        "tx_rate_mbps": 3.8,
        ...
      }
    ],
    "services": [...],
    "dhcp_clients": [...],
    "dns_stats": [...]
  }
}
```

## Database Schema

The WebUI uses PostgreSQL with automatic migrations (see `backend/migrations/`). Tables include:

- **Metrics and history:** `system_metrics`, `interface_stats`, `dhcp_leases`, `service_status`, and related time-series tables for bandwidth and history
- **Configuration (stored in DB after migration):** Apprise services, DNS zones/records, DHCP networks/reservations, notification rules
- **Device overrides:** Hostnames and overrides for devices
- **Indexes:** Optimized for time-series and config queries

On first startup, the backend can migrate Apprise, DNS, and DHCP configuration from `router-config.nix` / config files into the database; after that, those settings are managed via the WebUI.

## Configuration

### Backend Environment Variables

```bash
# Core
DATABASE_URL=postgresql+asyncpg://user:pass@host/db
JWT_SECRET_KEY=your-secret-key
JWT_ALGORITHM=HS256
JWT_EXPIRATION_MINUTES=1440
DEBUG=false

# Collection and paths
COLLECTION_INTERVAL=5
DNSMASQ_LEASE_FILES=/var/lib/dnsmasq/homelab/dhcp.leases /var/lib/dnsmasq/lan/dhcp.leases
ROUTER_CONFIG_FILE=/etc/nixos/router-config.nix

# Redis (required for Celery and caching)
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=          # optional
REDIS_WRITE_BUFFER_ENABLED=true
REDIS_BUFFER_FLUSH_INTERVAL=5
REDIS_BUFFER_MAX_SIZE=100

# Celery (worker/beat use these; backend uses Redis for cache)
# BROKER_URL or CELERY_BROKER_URL typically points to Redis, e.g. redis://localhost:6379/0
```

### Frontend Environment Variables

```bash
VITE_API_URL=http://localhost:8080
VITE_WS_URL=ws://localhost:8080/ws
```

## Troubleshooting

### Backend Issues

```bash
# Check service status
sudo systemctl status router-webui-backend

# View logs
sudo journalctl -u router-webui-backend -f

# Test database connection
psql -h localhost -U router_webui -d router_webui -c "SELECT COUNT(*) FROM system_metrics;"
```

### Celery Workers

```bash
sudo systemctl status router-webui-celery-worker
sudo systemctl status router-webui-celery-beat
journalctl -u router-webui-celery-worker -f
```

### Frontend Issues

```bash
# Check if backend is accessible
curl http://localhost:8080/api/health

# Rebuild frontend
cd webui/frontend
rm -rf node_modules dist
npm install
npm run build
```

### WebSocket Connection Issues

1. Verify JWT token is valid
2. Check firewall allows port 8080
3. Ensure backend service is running
4. Check browser console for errors

## Performance

### Backend
- ~50-80MB RAM usage (backend only; workers additional)
- Configurable collection interval (default 5 seconds)
- Async I/O for non-blocking operations
- Database connection pooling
- Redis caching for API responses

### Frontend
- Minimal bundle size with Vite
- Lazy-loaded routes
- Efficient WebSocket reconnection
- Buffered metrics for sparklines (last 60 points)

## Security

- PAM-based authentication
- JWT tokens with configurable expiration
- HTTPS support (via reverse proxy)
- Systemd security hardening (NoNewPrivileges, ProtectSystem, etc.)
- CORS configuration for development
- SQL injection prevention (SQLAlchemy ORM)
- XSS protection (React escaping)

## Contributing

This is part of the NixOS router project. Follow the main project's contribution guidelines.

## License

Same as the parent project.

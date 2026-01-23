"""
Main FastAPI application for Router WebUI
"""
import logging
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware

from .config import settings

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

# Enable verbose logging for Apprise (equivalent to -vvvv)
# Set Apprise logger to DEBUG level for maximum verbosity
apprise_logger = logging.getLogger('apprise')
apprise_logger.setLevel(logging.DEBUG)

# Also enable debug for apprise.plugins and apprise.attachment modules
logging.getLogger('apprise.plugins').setLevel(logging.DEBUG)
logging.getLogger('apprise.attachment').setLevel(logging.DEBUG)

# Disable SQLAlchemy engine INFO logging (suppress INSERT/UPDATE/DELETE statements)
# Only show WARNING and above for SQLAlchemy engine and related loggers
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.pool').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.dialects').setLevel(logging.WARNING)
logging.getLogger('sqlalchemy.orm').setLevel(logging.WARNING)
from .database import init_db, AsyncSessionLocal
from .websocket import manager, websocket_endpoint
from .api.auth import router as auth_router
from .api.history import router as history_router
from .api.bandwidth import router as bandwidth_router
from .api.devices import router as devices_router
from .api.system import router as system_router
from .api.speedtest import router as speedtest_router
from .api.cake import router as cake_router
from .api.apprise import router as apprise_router
from .api.notifications import router as notifications_router
from .api.dns import router as dns_router
from .api.dhcp import router as dhcp_router
from .api.cake_config import router as cake_config_router
from .api.apprise_config import router as apprise_config_router
from .api.dyndns_config import router as dyndns_config_router
from .api.port_forwarding import router as port_forwarding_router
from .api.blocklists import router as blocklists_router
from .api.whitelist import router as whitelist_router
from .utils.redis_client import close_redis_client
from .utils.apprise import migrate_secrets_to_database
from .utils.dns import migrate_dns_config_to_database
from .utils.dhcp import migrate_dhcp_config_to_database


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager
    
    Handles startup and shutdown events
    """
    # Startup
    print(f"Starting {settings.app_name}...")
    
    # Initialize database
    await init_db()
    
    # Migrate Apprise services from secrets/config file to database
    try:
        async with AsyncSessionLocal() as session:
            await migrate_secrets_to_database(session)
    except Exception as e:
        logging.getLogger(__name__).error(
            f"Error migrating Apprise services: {e}", exc_info=True
        )
        # Don't fail startup if migration fails
    
    # Migrate DNS configuration from router-config.nix to database
    try:
        async with AsyncSessionLocal() as session:
            await migrate_dns_config_to_database(session)
    except Exception as e:
        logging.getLogger(__name__).error(
            f"Error migrating DNS configuration: {e}", exc_info=True
        )
        # Don't fail startup if migration fails
    
    # Migrate DHCP configuration from router-config.nix to database
    try:
        async with AsyncSessionLocal() as session:
            await migrate_dhcp_config_to_database(session)
    except Exception as e:
        logging.getLogger(__name__).error(
            f"Error migrating DHCP configuration: {e}", exc_info=True
        )
        # Don't fail startup if migration fails
    
    # Start WebSocket broadcast loop
    await manager.start_broadcasting()
    print("WebSocket broadcaster started")
    
    # Note: Background workers now run as separate Celery processes
    # See router-webui-celery-worker.service and router-webui-celery-beat.service
    
    yield
    
    # Shutdown
    print("Shutting down...")
    
    await manager.stop_broadcasting()
    print("WebSocket broadcaster stopped")
    
    # Close Redis client connection
    await close_redis_client()
    print("Redis client closed")


# Create FastAPI app
# Disable default /docs and /redoc routes to avoid conflict with our documentation site
app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Router monitoring and management interface",
    lifespan=lifespan,
    docs_url="/api/docs",  # Move API docs to /api/docs instead of /docs
    redoc_url="/api/redoc"  # Move ReDoc to /api/redoc
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routers
app.include_router(auth_router)
app.include_router(history_router)
app.include_router(bandwidth_router)
app.include_router(devices_router)
app.include_router(system_router)
app.include_router(speedtest_router)
app.include_router(cake_router)
app.include_router(apprise_router)
app.include_router(notifications_router)
app.include_router(dns_router)
app.include_router(dhcp_router)
app.include_router(cake_config_router)
app.include_router(apprise_config_router)
app.include_router(dyndns_config_router)
app.include_router(port_forwarding_router)
app.include_router(blocklists_router)
app.include_router(whitelist_router)


@app.get("/api")
async def root():
    """API root endpoint"""
    return {
        "name": settings.app_name,
        "version": "1.0.0",
        "status": "operational"
    }


@app.get("/api/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "active_connections": len(manager.active_connections)
    }


@app.websocket("/ws")
async def websocket_route(
    websocket: WebSocket,
    token: str = Query(..., description="JWT authentication token")
):
    """WebSocket endpoint for real-time metrics
    
    Args:
        websocket: WebSocket connection
        token: JWT token for authentication
    """
    await websocket_endpoint(websocket, token)

# Note: Static file serving (frontend and docs) is now handled by nginx
# FastAPI only handles API routes and WebSocket connections


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug
    )


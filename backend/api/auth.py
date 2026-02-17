"""
Authentication API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Request, status
from ..models import LoginRequest, LoginResponse
from ..auth import authenticate_user, get_current_user
from ..utils.redis_client import get as redis_get, set as redis_set, delete as redis_delete


router = APIRouter(prefix="/api/auth", tags=["authentication"])

# Rate limiting for login: max attempts per IP per window
LOGIN_RATE_LIMIT_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 900  # 15 minutes


def _client_ip(request: Request) -> str:
    """Get client IP, respecting X-Forwarded-For when behind nginx."""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


@router.post("/login", response_model=LoginResponse)
async def login(request: Request, credentials: LoginRequest):
    """Login endpoint - authenticate user and return JWT token
    
    Rate limited: after 5 failed attempts per IP, returns 429 for 15 minutes.
    
    Args:
        request: FastAPI request (for client IP)
        credentials: Username and password
        
    Returns:
        LoginResponse: JWT access token and user info
    """
    ip = _client_ip(request)
    key = f"login_failures:{ip}"
    failures_raw = await redis_get(key)
    count = int(failures_raw) if failures_raw else 0

    if count >= LOGIN_RATE_LIMIT_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Try again in 15 minutes.",
        )

    try:
        result = await authenticate_user(credentials)
        await redis_delete(key)
        return result
    except HTTPException as e:
        if e.status_code == 401:
            await redis_set(key, str(count + 1), ttl=LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        raise


@router.get("/me")
async def get_me(current_user: str = Depends(get_current_user)):
    """Get current user information
    
    Args:
        current_user: Current authenticated user (from dependency)
        
    Returns:
        dict: Current user info
    """
    return {"username": current_user}


@router.post("/logout")
async def logout(current_user: str = Depends(get_current_user)):
    """Logout endpoint (client should discard token)
    
    Args:
        current_user: Current authenticated user (from dependency)
        
    Returns:
        dict: Success message
    """
    return {"message": "Successfully logged out"}


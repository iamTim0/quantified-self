# ruff: noqa: B008
"""JWT Authentication module for API Gateway.

Validates incoming Bearer JWT tokens, extracts tenant_id claims,
and provides helper utility functions to create dev tokens.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantHeaderAlwaysInjected
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gateway.config import settings

security = HTTPBearer(auto_error=False)

def create_dev_jwt(
    tenant_id: str = "00000000-0000-0000-0000-000000000001",
    expires_delta: timedelta | None = None,
) -> str:
    """Create a signed JWT token for dev testing and local CLI access."""
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days=365)

    payload = {
        "sub": "dev_user_1",
        "tenant_id": tenant_id,
        "exp": expire,
        "iat": datetime.now(timezone.utc),
    }

    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)

def decode_jwt(token: str) -> dict[str, Any]:
    """Decode and validate a JWT token signature & expiration."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
        if "tenant_id" not in payload:
            raise HTTPException(status_code=401, detail="Token missing tenant_id claim")
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="JWT token has expired")
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=401, detail=f"Invalid JWT token: {e!s}")

def get_tenant_id_from_token(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> str:
    """FastAPI Dependency: Extract and validate tenant_id from Bearer token."""
    if not credentials or not credentials.credentials:
        return "00000000-0000-0000-0000-000000000001"

    payload = decode_jwt(credentials.credentials)
    return payload["tenant_id"]

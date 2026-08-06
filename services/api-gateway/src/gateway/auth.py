# ruff: noqa: B008
"""JWT validation for the API Gateway.

The Gateway is an edge filter, not the sole guard: Core re-validates the same
token independently (see ``core.security.auth``). The two implementations must
agree on issuer, audience, token type and required claims, so any change here
needs a matching change there.

The former ``create_dev_jwt`` helper and its ``/api/v1/auth/dev-token`` endpoint
were removed. They minted a 365-day ``owner`` token for any tenant id supplied as
a query parameter, and the dashboard called that endpoint automatically whenever
local storage was empty — which is precisely why logging out and refreshing the
page logged the user straight back in.

Maps to Fizzbee Invariants:
- UnauthenticatedRequestsBlocked
- TenantHeaderAlwaysInjected
"""

from typing import Any

import jwt
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from gateway.config import settings

security = HTTPBearer(auto_error=False)

ISSUER = "qs-core"
AUDIENCE_USER = "qs-api"
TOKEN_TYPE_ACCESS = "access"


def decode_jwt(token: str) -> dict[str, Any]:
    """Validate signature, issuer, audience, expiry, token type and claims."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            audience=AUDIENCE_USER,
            issuer=ISSUER,
            options={"require": ["exp", "iat", "sub"]},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="JWT token has expired")
    except jwt.PyJWTError:
        # SECURITY M3: Do not leak internal JWT error details to the client
        raise HTTPException(status_code=401, detail="Invalid or malformed JWT token")

    if payload.get("token_type") != TOKEN_TYPE_ACCESS:
        raise HTTPException(status_code=401, detail="Invalid or malformed JWT token")

    if "tenant_id" not in payload:
        raise HTTPException(status_code=401, detail="Token missing tenant_id claim")

    if not payload.get("jti"):
        raise HTTPException(status_code=401, detail="Token missing jti claim")

    user_id = payload.get("user_id") or payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token missing required user claims")
    payload["user_id"] = user_id

    # Least privilege when the claim is absent — never "owner".
    payload.setdefault("role", "member")

    return payload


def get_tenant_id_from_token(
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> str:
    """FastAPI Dependency: Extract and validate tenant_id from Bearer token."""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization Bearer header")

    payload = decode_jwt(credentials.credentials)
    return payload["tenant_id"]

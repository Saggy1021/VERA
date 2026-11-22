# FILE: backend/auth/dependencies.py
# FastAPI Depends: require_proctor, require_candidate

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from auth.jwt_validator import validate_token, JWTPayload

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> JWTPayload:
    """Extract and validate the JWT from the Authorization header."""
    return validate_token(credentials.credentials)


async def require_proctor(
    user: JWTPayload = Depends(get_current_user),
) -> JWTPayload:
    """Dependency that ensures the authenticated user has the 'proctor' role."""
    if user.role != "proctor":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Proctor access required",
        )
    return user


async def require_candidate(
    user: JWTPayload = Depends(get_current_user),
) -> JWTPayload:
    """Dependency that ensures the authenticated user has the 'candidate' role."""
    if user.role != "candidate":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Candidate access required",
        )
    return user

# FILE: backend/auth/jwt_validator.py
# Validate Supabase JWT with JWKS (ES256) primary and legacy HS256 fallback

import jwt
from jwt import PyJWKClient
from fastapi import HTTPException, status
from config import settings
from typing import Optional
import logging

log = logging.getLogger(__name__)

_jwks_client: Optional[PyJWKClient] = None


def get_jwks_client() -> Optional[PyJWKClient]:
    """Lazy-initialize cached JWKS client for Supabase."""
    global _jwks_client
    if _jwks_client is None and settings.supabase_url:
        jwks_url = f"{settings.supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"
        _jwks_client = PyJWKClient(jwks_url, cache_jwk_set=True, lifespan=3600)
    return _jwks_client


class JWTPayload:
    """Parsed JWT payload from Supabase."""

    def __init__(self, user_id: str, role: str, email: str):
        self.user_id = user_id
        self.role = role
        self.email = email


def validate_token(token: str) -> JWTPayload:
    """
    Validate a Supabase JWT and extract user_id, role, and email.
    Supports Supabase's default asymmetric JWKS (ES256) as primary,
    with legacy symmetric secret (HS256) as fallback.
    """
    payload = None
    last_error = None

    # 1. Primary: Verify using Supabase JWKS (ES256 / RS256)
    try:
        client = get_jwks_client()
        if client:
            signing_key = client.get_signing_key_from_jwt(token)
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["ES256", "RS256"],
                audience="authenticated",
            )
    except Exception as e:
        last_error = e

    # 2. Fallback: Verify using Legacy HS256 secret
    if payload is None and settings.supabase_jwt_secret:
        try:
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                audience="authenticated",
            )
        except Exception as e:
            last_error = e

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(last_error)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim",
        )

    # Role can be in user_metadata or app_metadata
    user_metadata = payload.get("user_metadata", {})
    app_metadata = payload.get("app_metadata", {})
    role: str = user_metadata.get("role") or app_metadata.get("role") or payload.get("role", "")
    email: str = payload.get("email", "")

    if role not in ("proctor", "candidate"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid role in token: '{role}'",
        )

    return JWTPayload(user_id=user_id, role=role, email=email)

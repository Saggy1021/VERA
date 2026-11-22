# FILE: backend/auth/jwt_validator.py
# Validate Supabase JWT, extract role

from jose import jwt, JWTError
from fastapi import HTTPException, status
from config import settings
from typing import Optional


class JWTPayload:
    """Parsed JWT payload from Supabase."""

    def __init__(self, user_id: str, role: str, email: str):
        self.user_id = user_id
        self.role = role
        self.email = email


def validate_token(token: str) -> JWTPayload:
    """
    Validate a Supabase JWT and extract user_id, role, and email.
    Raises HTTPException 401 if the token is invalid or expired.
    """
    try:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret,
            algorithms=["HS256"],
            audience="authenticated",
        )
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {str(e)}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing 'sub' claim",
        )

    # Role is stored in user_metadata by Supabase Auth
    user_metadata = payload.get("user_metadata", {})
    role: str = user_metadata.get("role", "")
    email: str = payload.get("email", "")

    if role not in ("proctor", "candidate"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid role in token: '{role}'",
        )

    return JWTPayload(user_id=user_id, role=role, email=email)

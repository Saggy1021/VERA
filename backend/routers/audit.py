# FILE: backend/routers/audit.py
# Audit log read (proctor only)

from fastapi import APIRouter, Depends, Query
from typing import List

from auth.dependencies import require_proctor
from auth.jwt_validator import JWTPayload
from db import queries

router = APIRouter()


@router.get("/audit")
async def get_audit_log(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    user: JWTPayload = Depends(require_proctor),
):
    """Paginated audit log. Proctor only."""
    logs = await queries.get_audit_log(page=page, limit=limit)
    return logs

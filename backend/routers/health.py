# FILE: backend/routers/health.py
# /health, /ready endpoints

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Docker health check endpoint."""
    return {"status": "ok", "version": "1.0.0"}


@router.get("/ready")
async def readiness_check():
    """Readiness probe — checks if DB pool is initialized."""
    from database import get_pool
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        return {"status": "ready"}
    except Exception as e:
        return {"status": "not_ready", "error": str(e)}

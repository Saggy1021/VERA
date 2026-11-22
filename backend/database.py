# FILE: backend/database.py
# asyncpg pool + Supabase client init

import asyncpg
from typing import Optional

_pool: Optional[asyncpg.Pool] = None


async def init_db_pool(database_url: str) -> None:
    """Initialize the asyncpg connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )


async def close_db_pool() -> None:
    """Close the asyncpg connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    """Get the current connection pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_db_pool() first.")
    return _pool

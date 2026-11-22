# FILE: backend/database.py
# asyncpg pool + Supabase client init

import json
from typing import Optional
import asyncpg

_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Register JSON/JSONB codecs so columns return dicts/lists and strings don't double-encode."""
    await conn.set_type_codec(
        "json",
        encoder=lambda v: v if isinstance(v, str) else json.dumps(v),
        decoder=json.loads,
        schema="pg_catalog",
    )
    await conn.set_type_codec(
        "jsonb",
        encoder=lambda v: v if isinstance(v, str) else json.dumps(v),
        decoder=json.loads,
        schema="pg_catalog",
    )


async def init_db_pool(database_url: str) -> None:
    """Initialize the asyncpg connection pool."""
    global _pool
    # Supabase connection pooler requires SSL
    ssl_mode = "require" if "supabase" in database_url else None
    _pool = await asyncpg.create_pool(
        dsn=database_url,
        min_size=2,
        max_size=10,
        command_timeout=30,
        ssl=ssl_mode,
        init=_init_connection,
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

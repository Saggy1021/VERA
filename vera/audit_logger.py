"""
VERA — Audit Logger (Async PostgreSQL)
Every behavioral flag, score update, and session event is written to the
database. Required for GDPR Article 5 accountability and proctor review.
"""
import asyncio
import os
import time
import logging
import json

logger = logging.getLogger(__name__)

DB_URL = os.getenv(
    'VERA_DB_URL',
    'postgresql://vera_user:yourpassword@localhost:5432/vera_db'
)

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    candidate_id    TEXT,
    exam_id         TEXT,
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    ended_at        TIMESTAMPTZ,
    final_score     FLOAT,
    final_severity  TEXT,
    consent_given   BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS behavioral_events (
    id              BIGSERIAL PRIMARY KEY,
    session_id      TEXT REFERENCES sessions(session_id),
    event_time      TIMESTAMPTZ DEFAULT NOW(),
    event_type      TEXT NOT NULL,
    severity        TEXT,
    risk_score      FLOAT,
    details         JSONB,
    evidence_key    TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_session ON behavioral_events(session_id);
CREATE INDEX IF NOT EXISTS idx_events_time ON behavioral_events(event_time);
"""

try:
    import asyncpg
    _has_asyncpg = True
except ImportError:
    _has_asyncpg = False
    logger.warning("asyncpg not installed. Audit logging disabled.")


class AuditLogger:
    """
    Async audit trail logger using asyncpg + PostgreSQL.
    All writes are fire-and-forget (non-blocking) to not slow the pipeline.
    """

    def __init__(self):
        self._pool = None
        self._ready = False

    async def initialize(self):
        """Call once at server startup."""
        if not _has_asyncpg:
            logger.warning("AuditLogger: asyncpg not available. Running WITHOUT audit logging.")
            return
        try:
            self._pool = await asyncpg.create_pool(DB_URL, min_size=2, max_size=10)
            async with self._pool.acquire() as conn:
                await conn.execute(CREATE_TABLES_SQL)
            self._ready = True
            logger.info("AuditLogger: PostgreSQL connection pool ready.")
        except Exception as e:
            logger.error(f"AuditLogger: DB init failed: {e}")
            logger.warning("AuditLogger: Running WITHOUT audit logging. Fix DB config.")

    async def log_session_start(self, session_id: str, candidate_id: str,
                                exam_id: str, consent_given: bool):
        if not self._ready:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO sessions (session_id, candidate_id, exam_id, consent_given)
                       VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING""",
                    session_id, candidate_id, exam_id, consent_given
                )
        except Exception as e:
            logger.error(f"AuditLogger.log_session_start: {e}")

    async def log_event(self, session_id: str, event_type: str,
                        severity: str, risk_score: float,
                        details: dict, evidence_key: str = None):
        if not self._ready:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """INSERT INTO behavioral_events
                       (session_id, event_type, severity, risk_score, details, evidence_key)
                       VALUES ($1, $2, $3, $4, $5, $6)""",
                    session_id, event_type, severity, risk_score,
                    json.dumps(details), evidence_key
                )
        except Exception as e:
            logger.error(f"AuditLogger.log_event: {e}")

    async def log_session_end(self, session_id: str, final_score: float,
                              final_severity: str):
        if not self._ready:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """UPDATE sessions SET ended_at=NOW(),
                       final_score=$2, final_severity=$3
                       WHERE session_id=$1""",
                    session_id, final_score, final_severity
                )
        except Exception as e:
            logger.error(f"AuditLogger.log_session_end: {e}")

    async def get_session_events(self, session_id: str) -> list:
        if not self._ready:
            return []
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT * FROM behavioral_events
                   WHERE session_id=$1 ORDER BY event_time ASC""",
                session_id
            )
        return [dict(r) for r in rows]

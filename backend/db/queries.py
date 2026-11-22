# FILE: backend/db/queries.py
# Named SQL query functions

import json
from typing import Optional, List
from uuid import UUID
from datetime import datetime

from database import get_pool


# ── SESSIONS ──────────────────────────────────────

async def create_session(
    proctor_id: str, title: str, session_type: str,
    scheduled_at: datetime, duration_min: int,
    description: Optional[str] = None, settings: Optional[dict] = None
) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO public.sessions (proctor_id, title, description, type, scheduled_at, duration_min, settings)
        VALUES ($1, $2, $3, $4::session_type, $5, $6, $7::jsonb)
        RETURNING *
        """,
        proctor_id, title, description, session_type, scheduled_at,
        duration_min, json.dumps(settings or {})
    )
    return dict(row)


async def get_session(session_id: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM public.sessions WHERE id = $1", session_id
    )
    return dict(row) if row else None


async def list_sessions_by_proctor(proctor_id: str) -> List[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        "SELECT * FROM public.sessions WHERE proctor_id = $1 ORDER BY created_at DESC",
        proctor_id
    )
    return [dict(r) for r in rows]


async def list_sessions_by_candidate(candidate_id: str) -> List[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT s.* FROM public.sessions s
        JOIN public.session_candidates sc ON sc.session_id = s.id
        WHERE sc.candidate_id = $1
        ORDER BY s.scheduled_at DESC
        """,
        candidate_id
    )
    return [dict(r) for r in rows]


async def update_session_status(
    session_id: str, status: str, proctor_id: str
) -> Optional[dict]:
    pool = get_pool()
    extra_fields = ""
    if status == "active":
        extra_fields = ", started_at = NOW()"
    elif status in ("completed", "cancelled"):
        extra_fields = ", ended_at = NOW()"

    row = await pool.fetchrow(
        f"""
        UPDATE public.sessions
        SET status = $1::session_status{extra_fields}
        WHERE id = $2 AND proctor_id = $3
        RETURNING *
        """,
        status, session_id, proctor_id
    )
    return dict(row) if row else None


# ── SESSION CANDIDATES ────────────────────────────

async def invite_candidate(session_id: str, candidate_id: str) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO public.session_candidates (session_id, candidate_id)
        VALUES ($1, $2)
        ON CONFLICT (session_id, candidate_id) DO NOTHING
        RETURNING *
        """,
        session_id, candidate_id
    )
    return dict(row) if row else {}


async def get_candidate_by_email(email: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM public.profiles WHERE email = $1 AND role = 'candidate'",
        email
    )
    return dict(row) if row else None


async def list_session_candidates(session_id: str) -> List[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT sc.*, p.full_name, p.email, p.avatar_url
        FROM public.session_candidates sc
        JOIN public.profiles p ON p.id = sc.candidate_id
        WHERE sc.session_id = $1
        """,
        session_id
    )
    return [dict(r) for r in rows]


async def enroll_candidate(
    session_id: str, candidate_id: str, face_descriptor: list
) -> bool:
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE public.session_candidates
        SET face_descriptor = $1::jsonb, enrolled_at = NOW()
        WHERE session_id = $2 AND candidate_id = $3
        """,
        json.dumps(face_descriptor), session_id, candidate_id
    )
    return "UPDATE 1" in result


async def mark_candidate_joined(session_id: str, candidate_id: str) -> bool:
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE public.session_candidates
        SET joined_at = NOW()
        WHERE session_id = $1 AND candidate_id = $2
        """,
        session_id, candidate_id
    )
    return "UPDATE 1" in result


async def mark_candidate_left(session_id: str, candidate_id: str) -> bool:
    pool = get_pool()
    result = await pool.execute(
        """
        UPDATE public.session_candidates
        SET left_at = NOW()
        WHERE session_id = $1 AND candidate_id = $2
        """,
        session_id, candidate_id
    )
    return "UPDATE 1" in result


# ── MALPRACTICE EVENTS ────────────────────────────

async def insert_event(
    session_id: str, candidate_id: str, event_type: str,
    severity: str, risk_score: int, description: Optional[str] = None,
    metadata: Optional[dict] = None, screenshot_url: Optional[str] = None,
    gemini_verdict: Optional[str] = None, occurred_at: Optional[datetime] = None
) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO public.malpractice_events
        (session_id, candidate_id, event_type, severity, risk_score,
         description, metadata, screenshot_url, gemini_verdict, occurred_at)
        VALUES ($1, $2, $3::event_type, $4::event_severity, $5,
                $6, $7::jsonb, $8, $9, COALESCE($10, NOW()))
        RETURNING *
        """,
        session_id, candidate_id, event_type, severity, risk_score,
        description, json.dumps(metadata or {}), screenshot_url,
        gemini_verdict, occurred_at
    )
    return dict(row)


async def insert_events_batch(
    events: list, candidate_id: str
) -> int:
    pool = get_pool()
    count = 0
    async with pool.acquire() as conn:
        async with conn.transaction():
            for event in events:
                await conn.execute(
                    """
                    INSERT INTO public.malpractice_events
                    (session_id, candidate_id, event_type, severity, risk_score,
                     description, metadata, screenshot_url, occurred_at)
                    VALUES ($1, $2, $3::event_type, $4::event_severity, $5,
                            $6, $7::jsonb, $8, COALESCE($9, NOW()))
                    """,
                    str(event.session_id), candidate_id, event.event_type.value,
                    event.severity.value, event.risk_score,
                    event.description, json.dumps(event.metadata or {}),
                    event.screenshot_url, event.occurred_at
                )
                count += 1
    return count


async def get_session_events(session_id: str) -> List[dict]:
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM public.malpractice_events
        WHERE session_id = $1
        ORDER BY occurred_at ASC
        """,
        session_id
    )
    return [dict(r) for r in rows]


async def get_recent_high_events(session_id: str, minutes: int = 30) -> List[dict]:
    """
    C1: Fetch recent HIGH/CRITICAL events for the missed-events reconnect feature.
    Called when a proctor rejoins a Socket.IO room after a disconnect.
    Returns events in chronological order so the alert feed reconstructs correctly.
    """
    pool = get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM public.malpractice_events
        WHERE session_id = $1
          AND severity IN ('high', 'critical')
          AND occurred_at > NOW() - INTERVAL '1 minute' * $2
        ORDER BY occurred_at ASC
        """,
        session_id, minutes
    )
    return [dict(r) for r in rows]




# ── REPORTS ───────────────────────────────────────

async def get_report(session_id: str, candidate_id: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        SELECT * FROM public.reports
        WHERE session_id = $1 AND candidate_id = $2
        """,
        session_id, candidate_id
    )
    return dict(row) if row else None


async def create_report(
    session_id: str, candidate_id: str, overall_score: int,
    summary: str, event_count: dict, timeline: list
) -> dict:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO public.reports
        (session_id, candidate_id, overall_score, summary, event_count, timeline)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
        ON CONFLICT DO NOTHING
        RETURNING *
        """,
        session_id, candidate_id, overall_score, summary,
        json.dumps(event_count), json.dumps(timeline)
    )
    return dict(row) if row else {}


async def publish_report(session_id: str, candidate_id: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        UPDATE public.reports
        SET status = 'published', published_at = NOW()
        WHERE session_id = $1 AND candidate_id = $2
        RETURNING *
        """,
        session_id, candidate_id
    )
    return dict(row) if row else None


async def suppress_report(session_id: str, candidate_id: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        """
        UPDATE public.reports
        SET status = 'suppressed'
        WHERE session_id = $1 AND candidate_id = $2
        RETURNING *
        """,
        session_id, candidate_id
    )
    return dict(row) if row else None


# ── AUDIT LOG ─────────────────────────────────────

async def insert_audit_log(
    actor_id: str, actor_role: str, action: str,
    resource: Optional[str] = None, resource_id: Optional[str] = None,
    ip_address: Optional[str] = None, user_agent: Optional[str] = None
) -> None:
    pool = get_pool()
    await pool.execute(
        """
        INSERT INTO public.audit_log
        (actor_id, actor_role, action, resource, resource_id, ip_address, user_agent)
        VALUES ($1, $2::user_role, $3, $4, $5, $6::inet, $7)
        """,
        actor_id, actor_role, action, resource, resource_id,
        ip_address, user_agent
    )


async def get_audit_log(page: int = 1, limit: int = 50) -> List[dict]:
    pool = get_pool()
    offset = (page - 1) * limit
    rows = await pool.fetch(
        """
        SELECT * FROM public.audit_log
        ORDER BY created_at DESC
        LIMIT $1 OFFSET $2
        """,
        limit, offset
    )
    return [dict(r) for r in rows]


# ── PROFILES ──────────────────────────────────────

async def get_profile(user_id: str) -> Optional[dict]:
    pool = get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM public.profiles WHERE id = $1", user_id
    )
    return dict(row) if row else None

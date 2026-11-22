# FILE: backend/routers/sessions.py
# CRUD: create/list/get sessions

from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import List
from uuid import UUID

from auth.dependencies import require_proctor, require_candidate, get_current_user
from auth.jwt_validator import JWTPayload
from models.session import SessionCreate, SessionResponse, SessionStatusUpdate
from db import queries

router = APIRouter()


@router.post("/sessions", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreate,
    request: Request,
    user: JWTPayload = Depends(require_proctor),
):
    """Create a new exam/interview session. Proctor only."""
    session = await queries.create_session(
        proctor_id=user.user_id,
        title=body.title,
        session_type=body.type.value,
        scheduled_at=body.scheduled_at,
        duration_min=body.duration_min,
        description=body.description,
        settings=body.settings,
    )

    # Audit log
    await queries.insert_audit_log(
        actor_id=user.user_id,
        actor_role="proctor",
        action="create_session",
        resource="sessions",
        resource_id=str(session["id"]),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return session


@router.get("/sessions", response_model=List[SessionResponse])
async def list_sessions(
    user: JWTPayload = Depends(get_current_user),
):
    """List sessions. Proctors see own sessions, candidates see their assigned sessions."""
    if user.role == "proctor":
        return await queries.list_sessions_by_proctor(user.user_id)
    else:
        return await queries.list_sessions_by_candidate(user.user_id)


@router.get("/sessions/{session_id}", response_model=SessionResponse)
async def get_session(
    session_id: UUID,
    user: JWTPayload = Depends(get_current_user),
):
    """Get a single session by ID."""
    session = await queries.get_session(str(session_id))
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Access control: proctor must own it, candidate must be assigned
    if user.role == "proctor" and str(session["proctor_id"]) != user.user_id:
        raise HTTPException(status_code=403, detail="Not your session")
    elif user.role == "candidate":
        candidates = await queries.list_session_candidates(str(session_id))
        candidate_ids = [str(c["candidate_id"]) for c in candidates]
        if user.user_id not in candidate_ids:
            raise HTTPException(status_code=403, detail="Not assigned to this session")

    return session


@router.patch("/sessions/{session_id}/status", response_model=SessionResponse)
async def update_session_status(
    session_id: UUID,
    body: SessionStatusUpdate,
    request: Request,
    user: JWTPayload = Depends(require_proctor),
):
    """Update session status (start/end/cancel). Proctor only."""
    session = await queries.update_session_status(
        session_id=str(session_id),
        status=body.status.value,
        proctor_id=user.user_id,
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or not yours")

    await queries.insert_audit_log(
        actor_id=user.user_id,
        actor_role="proctor",
        action=f"update_session_status:{body.status.value}",
        resource="sessions",
        resource_id=str(session_id),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    # B10: Auto-generate draft reports for all candidates when session completes.
    # Runs synchronously in the same request — report generation is a fast DB
    # aggregation query (not an ML call). Idempotent: skips if already exists.
    if body.status.value == "completed":
        from services.report_service import generate_draft_report
        candidates = await queries.list_session_candidates(str(session_id))
        for c in candidates:
            await generate_draft_report(
                db=None,  # queries module manages its own pool
                session_id=str(session_id),
                candidate_id=str(c["candidate_id"]),
            )

    return session


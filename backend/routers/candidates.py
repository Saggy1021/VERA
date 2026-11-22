# FILE: backend/routers/candidates.py
# Invite candidates, get candidate sessions

from fastapi import APIRouter, Depends, HTTPException, status, Request
from typing import List
from uuid import UUID

from auth.dependencies import require_proctor, require_candidate
from auth.jwt_validator import JWTPayload
from models.candidate import CandidateInvite, EnrollmentData, SessionCandidateResponse
from db import queries

router = APIRouter()


@router.post(
    "/sessions/{session_id}/candidates",
    response_model=SessionCandidateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def invite_candidate(
    session_id: UUID,
    body: CandidateInvite,
    request: Request,
    user: JWTPayload = Depends(require_proctor),
):
    """Invite a candidate to a session by email. Proctor only."""
    # Verify proctor owns this session
    session = await queries.get_session(str(session_id))
    if not session or str(session["proctor_id"]) != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found or not yours")

    # Find candidate profile by email
    candidate = await queries.get_candidate_by_email(body.email)
    if not candidate:
        raise HTTPException(
            status_code=404,
            detail=f"No candidate account found for email: {body.email}",
        )

    result = await queries.invite_candidate(
        session_id=str(session_id),
        candidate_id=str(candidate["id"]),
    )
    if not result:
        raise HTTPException(
            status_code=409,
            detail="Candidate already invited to this session",
        )

    # Audit log
    await queries.insert_audit_log(
        actor_id=user.user_id,
        actor_role="proctor",
        action="invite_candidate",
        resource="session_candidates",
        resource_id=str(result.get("id", "")),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return result


@router.get(
    "/sessions/{session_id}/candidates",
    response_model=List[SessionCandidateResponse],
)
async def list_candidates(
    session_id: UUID,
    user: JWTPayload = Depends(require_proctor),
):
    """List all invited candidates for a session. Proctor only."""
    session = await queries.get_session(str(session_id))
    if not session or str(session["proctor_id"]) != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found or not yours")

    return await queries.list_session_candidates(str(session_id))


@router.post("/setup/enroll")
async def enroll_face(
    body: EnrollmentData,
    user: JWTPayload = Depends(require_candidate),
):
    """
    Store enrollment face descriptor. Candidate only.
    The 128-dim face descriptor is computed in the browser by face-api.js
    and only the number array is sent to the server.
    NO raw face photos are sent to any external API.
    """
    success = await queries.enroll_candidate(
        session_id=str(body.session_id),
        candidate_id=user.user_id,
        face_descriptor=body.face_descriptor,
    )
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Session candidate record not found",
        )

    return {"ok": True}

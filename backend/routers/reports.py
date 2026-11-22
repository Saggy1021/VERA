# FILE: backend/routers/reports.py
# Generate/publish/fetch reports

from fastapi import APIRouter, Depends, HTTPException, Request
from uuid import UUID

from auth.dependencies import require_proctor, get_current_user
from auth.jwt_validator import JWTPayload
from models.report import ReportResponse
from db import queries
from services.report_service import build_report

router = APIRouter()


@router.get("/reports/{session_id}/{candidate_id}", response_model=ReportResponse)
async def get_report(
    session_id: UUID,
    candidate_id: UUID,
    user: JWTPayload = Depends(get_current_user),
):
    """
    Get report for a session/candidate.
    Proctor sees all reports for their sessions.
    Candidate only sees published reports for themselves.
    """
    report = await queries.get_report(str(session_id), str(candidate_id))

    if not report:
        # Try to auto-generate if proctor is requesting
        if user.role == "proctor":
            session = await queries.get_session(str(session_id))
            if not session or str(session["proctor_id"]) != user.user_id:
                raise HTTPException(status_code=404, detail="Session not found or not yours")

            report = await build_report(str(session_id), str(candidate_id))
            if not report:
                raise HTTPException(status_code=404, detail="No events found to generate report")
        else:
            raise HTTPException(status_code=404, detail="Report not available")

    # Access control
    if user.role == "proctor":
        session = await queries.get_session(str(session_id))
        if not session or str(session["proctor_id"]) != user.user_id:
            raise HTTPException(status_code=403, detail="Not your session")
    elif user.role == "candidate":
        if str(candidate_id) != user.user_id:
            raise HTTPException(status_code=403, detail="Not your report")
        if report.get("status") != "published":
            raise HTTPException(status_code=404, detail="Report not available")

    return report


@router.post("/reports/{session_id}/{candidate_id}/publish", response_model=ReportResponse)
async def publish_report(
    session_id: UUID,
    candidate_id: UUID,
    request: Request,
    user: JWTPayload = Depends(require_proctor),
):
    """Publish report to candidate. Proctor only."""
    session = await queries.get_session(str(session_id))
    if not session or str(session["proctor_id"]) != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found or not yours")

    # Ensure report exists (auto-generate if needed)
    report = await queries.get_report(str(session_id), str(candidate_id))
    if not report:
        report = await build_report(str(session_id), str(candidate_id))
        if not report:
            raise HTTPException(status_code=404, detail="Cannot generate report — no events found")

    published = await queries.publish_report(str(session_id), str(candidate_id))
    if not published:
        raise HTTPException(status_code=500, detail="Failed to publish report")

    await queries.insert_audit_log(
        actor_id=user.user_id,
        actor_role="proctor",
        action="publish_report",
        resource="reports",
        resource_id=str(published["id"]),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return published


@router.post("/reports/{session_id}/{candidate_id}/suppress", response_model=ReportResponse)
async def suppress_report(
    session_id: UUID,
    candidate_id: UUID,
    request: Request,
    user: JWTPayload = Depends(require_proctor),
):
    """Suppress report — candidate sees 'Report not available'. Proctor only."""
    session = await queries.get_session(str(session_id))
    if not session or str(session["proctor_id"]) != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found or not yours")

    suppressed = await queries.suppress_report(str(session_id), str(candidate_id))
    if not suppressed:
        raise HTTPException(status_code=404, detail="Report not found")

    await queries.insert_audit_log(
        actor_id=user.user_id,
        actor_role="proctor",
        action="suppress_report",
        resource="reports",
        resource_id=str(suppressed["id"]),
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return suppressed

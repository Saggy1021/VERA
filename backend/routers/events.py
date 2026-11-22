# FILE: backend/routers/events.py
# Receive malpractice events from browser

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from uuid import UUID

from auth.dependencies import require_candidate, require_proctor
from auth.jwt_validator import JWTPayload
from models.event import MalpracticeEventBatch, HighSeverityEvent, MalpracticeEventResponse
from db import queries
from services.gemini_service import analyze_screenshot
from services.storage_service import upload_screenshot, upload_clip
from typing import List

router = APIRouter()


@router.post("/events/batch")
async def receive_events_batch(
    body: MalpracticeEventBatch,
    user: JWTPayload = Depends(require_candidate),
):
    """
    Bulk event ingest (called every 10s from browser).
    Prevents API flooding during fast head movements.
    """
    count = await queries.insert_events_batch(
        events=body.events,
        candidate_id=user.user_id,
    )
    return {"received": count}


@router.post("/events/high")
async def receive_high_event(
    body: HighSeverityEvent,
    request: Request,
    user: JWTPayload = Depends(require_candidate),
):
    """
    Receive a HIGH severity event with screenshot.
    Triggers Gemini call + Supabase Storage upload.
    Gemini failure must NEVER crash the event handler.
    """
    http_client = request.app.state.http_client

    # Upload screenshot to storage
    evidence_url = None
    try:
        evidence_url = await upload_screenshot(
            screenshot_b64=body.screenshot,
            session_id=str(body.session_id),
            candidate_id=user.user_id,
        )
    except Exception:
        # Storage failure is non-fatal
        pass

    # Call Gemini for AI second opinion — ONLY for HIGH events
    gemini_verdict = None
    try:
        gemini_result = await analyze_screenshot(
            screenshot_b64=body.screenshot,
            flag_types=[body.event_type.value],
            client=http_client,
        )
        if gemini_result.get("status") == "ok":
            gemini_verdict = gemini_result.get("verdict")
    except Exception:
        # IMPORTANT: Gemini failure must NEVER crash the event handler.
        # The event is still saved without a Gemini verdict.
        pass

    # Insert event with verdict and evidence URL
    event = await queries.insert_event(
        session_id=str(body.session_id),
        candidate_id=user.user_id,
        event_type=body.event_type.value,
        severity=body.severity.value,
        risk_score=body.risk_score,
        description=body.description,
        metadata=body.metadata,
        screenshot_url=evidence_url,
        gemini_verdict=gemini_verdict,
        occurred_at=body.occurred_at,
    )

    # Push event to proctor via Socket.IO
    try:
        from main import sio
        await sio.emit(
            "candidate_event",
            {
                "candidateId": user.user_id,
                "event": event,
            },
            room=str(body.session_id),
        )
    except Exception:
        pass

    return {
        "geminiVerdict": gemini_verdict,
        "evidenceUrl": evidence_url,
    }


@router.get(
    "/sessions/{session_id}/events",
    response_model=List[MalpracticeEventResponse],
)
async def get_session_events(
    session_id: UUID,
    user: JWTPayload = Depends(require_proctor),
):
    """Proctor views all events for a session."""
    session = await queries.get_session(str(session_id))
    if not session or str(session["proctor_id"]) != user.user_id:
        raise HTTPException(status_code=404, detail="Session not found or not yours")

    return await queries.get_session_events(str(session_id))


@router.post("/events/clip")
async def upload_evidence_clip(
    file: UploadFile = File(...),
    session_id: str = Form(...),
    event_type: str = Form(...),
    user: JWTPayload = Depends(require_candidate),
):
    """
    Receive a 30-second WebM clip from the circular buffer.
    Uploads to Supabase Storage. clip_url is nullable — failure here
    never affects the HIGH event pipeline.
    """
    if not file.content_type or "webm" not in file.content_type:
        # Accept even if browser sends generic application/octet-stream
        pass

    try:
        clip_bytes = await file.read()
        clip_url = await upload_clip(
            clip_bytes=clip_bytes,
            session_id=session_id,
            candidate_id=user.user_id,
            event_type=event_type,
            filename=file.filename or f"{session_id}_{event_type}.webm",
        )
        return {"clip_url": clip_url}
    except Exception as exc:
        # Non-fatal: log and return empty — never crash the event pipeline
        import logging
        logging.getLogger(__name__).warning("Clip upload failed: %s", exc)
        return {"clip_url": None}


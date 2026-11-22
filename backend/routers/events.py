# FILE: backend/routers/events.py
# Receive malpractice events from browser with non-blocking BackgroundTasks

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, BackgroundTasks
from uuid import UUID
from datetime import datetime
import json
import logging

from auth.dependencies import require_candidate, require_proctor
from auth.jwt_validator import JWTPayload
from models.event import MalpracticeEventBatch, HighSeverityEvent, MalpracticeEventResponse
from db import queries
from services.gemini_service import analyze_screenshot
from services.storage_service import upload_screenshot, upload_clip
from typing import List

log = logging.getLogger(__name__)
router = APIRouter()


def serialize_event_for_socket(event: dict) -> dict:
    """Safely convert database row dict to JSON-serializable socket payload."""
    serialized = {}
    for k, v in event.items():
        if isinstance(v, UUID):
            serialized[k] = str(v)
        elif isinstance(v, datetime):
            serialized[k] = v.isoformat()
        else:
            serialized[k] = v
    return serialized


async def process_high_event_background(
    event_id: str,
    screenshot_b64: str,
    session_id: str,
    candidate_id: str,
    event_type: str,
    http_client=None,
):
    """
    Background Task: Uploads screenshot to storage and calls Gemini API.
    Updates the database row and emits an updated event to proctors.
    Runs completely outside the HTTP request lifecycle.
    """
    evidence_url = None
    try:
        evidence_url = await upload_screenshot(
            screenshot_b64=screenshot_b64,
            session_id=session_id,
            candidate_id=candidate_id,
        )
    except Exception as e:
        log.warning(f"[Background] Screenshot upload error: {e}")

    gemini_verdict = None
    try:
        gemini_result = await analyze_screenshot(
            screenshot_b64=screenshot_b64,
            flag_types=[event_type],
            client=http_client,
        )
        if gemini_result.get("status") == "ok":
            gemini_verdict = gemini_result.get("verdict")
    except Exception as e:
        log.warning(f"[Background] Gemini analysis error: {e}")

    # Update event row in DB with evidence URL and Gemini verdict
    try:
        updated_event = await queries.update_event_evidence(
            event_id=event_id,
            screenshot_url=evidence_url,
            gemini_verdict=gemini_verdict,
        )
        if updated_event:
            from main import sio
            await sio.emit(
                "candidate_event",
                {
                    "candidateId": candidate_id,
                    "event": serialize_event_for_socket(dict(updated_event)),
                },
                room=f"session:{session_id}",
            )
    except Exception as e:
        log.error(f"[Background] Failed to update event row: {e}")


@router.post("/events/batch")
async def receive_events_batch(
    body: MalpracticeEventBatch,
    user: JWTPayload = Depends(require_candidate),
):
    """
    Bulk event ingest (called every 10s from browser).
    Prevents API flooding during fast head movements.
    Emits medium/high/critical events immediately to the session room.
    """
    count = await queries.insert_events_batch(
        events=body.events,
        candidate_id=user.user_id,
    )

    # Broadcast significant events to proctors immediately
    if body.events:
        try:
            from main import sio
            for e in body.events:
                sev = e.severity.value if hasattr(e.severity, "value") else str(e.severity)
                if sev in ("medium", "high", "critical"):
                    ev_type = e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type)
                    occurred_str = (
                        e.occurred_at.isoformat()
                        if e.occurred_at
                        else datetime.utcnow().isoformat()
                    )
                    await sio.emit(
                        "candidate_event",
                        {
                            "candidateId": user.user_id,
                            "event": {
                                "id": f"batch_{int(datetime.utcnow().timestamp()*1000)}_{ev_type}",
                                "session_id": str(e.session_id),
                                "candidate_id": user.user_id,
                                "event_type": ev_type,
                                "severity": sev,
                                "risk_score": e.risk_score,
                                "description": e.description,
                                "metadata": e.metadata or {},
                                "occurred_at": occurred_str,
                            },
                        },
                        room=f"session:{e.session_id}",
                    )
        except Exception as exc:
            log.warning("[receive_events_batch] Socket broadcast failed: %s", exc)

    return {"received": count}


@router.post("/events/high")
async def receive_high_event(
    body: HighSeverityEvent,
    request: Request,
    background_tasks: BackgroundTasks,
    user: JWTPayload = Depends(require_candidate),
):
    """
    Receive a HIGH severity event.
    Inserts event into database immediately and emits live alert to proctor.
    Heavy screenshot storage upload + Gemini analysis are offloaded to BackgroundTasks.
    Responds in < 15ms.
    """
    # 1. Insert base event into database immediately
    event = await queries.insert_event(
        session_id=str(body.session_id),
        candidate_id=user.user_id,
        event_type=body.event_type.value,
        severity=body.severity.value,
        risk_score=body.risk_score,
        description=body.description,
        metadata=body.metadata,
        screenshot_url=None,
        gemini_verdict=None,
        occurred_at=body.occurred_at,
    )

    serialized_event = serialize_event_for_socket(event)

    # 2. Push event immediately to proctors in the session room
    try:
        from main import sio
        await sio.emit(
            "candidate_event",
            {
                "candidateId": user.user_id,
                "event": serialized_event,
            },
            room=f"session:{body.session_id}",
        )
    except Exception as e:
        log.warning(f"Socket emit failed: {e}")

    # 3. Offload storage upload + Gemini analysis to BackgroundTasks
    http_client = getattr(request.app.state, "http_client", None)
    background_tasks.add_task(
        process_high_event_background,
        event_id=str(event["id"]),
        screenshot_b64=body.screenshot,
        session_id=str(body.session_id),
        candidate_id=user.user_id,
        event_type=body.event_type.value,
        http_client=http_client,
    )

    return {
        "status": "received",
        "eventId": str(event["id"]),
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
    Receive a 30-second WebM clip from circular buffer.
    Uploads to Supabase Storage via background thread.
    """
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
        log.warning("Clip upload failed: %s", exc)
        return {"clip_url": None}


@router.post("/events/transcribe")
async def transcribe_audio_chunk(
    request: Request,
    file: UploadFile = File(...),
    user: JWTPayload = Depends(require_candidate),
):
    """
    Receive 16kHz mono audio chunk from candidate microphone.
    Calls Groq Whisper for speech-to-text.
    Returns {"transcript": str | None} cleanly.
    """
    try:
        audio_bytes = await file.read()
        from services.groq_service import transcribe_audio
        http_client = getattr(request.app.state, "http_client", None)
        transcript = await transcribe_audio(audio_bytes=audio_bytes, client=http_client)
        return {"transcript": transcript}
    except Exception as exc:
        log.warning("[transcribe_audio_chunk] Transcription failed: %s", exc)
        return {"transcript": None}

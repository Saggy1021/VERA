# FILE: backend/models/event.py
# Pydantic models for MalpracticeEvent

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
from uuid import UUID


class EventSeverity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class EventType(str, Enum):
    no_face = "no_face"
    multiple_faces = "multiple_faces"
    head_turned = "head_turned"
    gaze_away = "gaze_away"
    tab_switch = "tab_switch"
    fullscreen_exit = "fullscreen_exit"
    object_detected = "object_detected"
    audio_activity = "audio_activity"
    second_speaker = "second_speaker"
    identity_mismatch = "identity_mismatch"
    copy_paste = "copy_paste"
    context_switch = "context_switch"
    session_end = "session_end"


class MalpracticeEventCreate(BaseModel):
    session_id: UUID
    event_type: EventType
    severity: EventSeverity
    risk_score: int = Field(default=0, ge=0, le=100)
    description: Optional[str] = None
    metadata: Optional[dict] = {}
    screenshot_url: Optional[str] = None
    occurred_at: Optional[datetime] = None


class MalpracticeEventBatch(BaseModel):
    events: List[MalpracticeEventCreate]


class HighSeverityEvent(BaseModel):
    session_id: UUID
    event_type: EventType
    severity: EventSeverity = EventSeverity.high
    risk_score: int = Field(default=0, ge=0, le=100)
    description: Optional[str] = None
    metadata: Optional[dict] = {}
    screenshot: str  # base64 JPEG
    occurred_at: Optional[datetime] = None


class MalpracticeEventResponse(BaseModel):
    id: UUID
    session_id: UUID
    candidate_id: UUID
    event_type: EventType
    severity: EventSeverity
    risk_score: int
    description: Optional[str]
    metadata: Optional[dict]
    screenshot_url: Optional[str]
    gemini_verdict: Optional[str]
    occurred_at: datetime

    class Config:
        from_attributes = True

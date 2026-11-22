# FILE: backend/models/session.py
# Pydantic models for Session

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum
from uuid import UUID


class SessionType(str, Enum):
    exam = "exam"
    interview = "interview"


class SessionStatus(str, Enum):
    scheduled = "scheduled"
    active = "active"
    completed = "completed"
    cancelled = "cancelled"


class SessionCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    type: SessionType = SessionType.exam
    scheduled_at: datetime
    duration_min: int = Field(default=60, ge=10, le=480)
    description: Optional[str] = None
    settings: Optional[dict] = {}


class SessionStatusUpdate(BaseModel):
    status: SessionStatus


class SessionResponse(BaseModel):
    id: UUID
    proctor_id: UUID
    title: str
    description: Optional[str]
    type: SessionType
    status: SessionStatus
    scheduled_at: datetime
    duration_min: int
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    settings: Optional[dict]
    created_at: datetime

    class Config:
        from_attributes = True

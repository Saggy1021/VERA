# FILE: backend/models/report.py
# Pydantic models for Report

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum
from uuid import UUID


class ReportStatus(str, Enum):
    draft = "draft"
    published = "published"
    suppressed = "suppressed"


class ReportResponse(BaseModel):
    id: UUID
    session_id: UUID
    candidate_id: UUID
    status: ReportStatus
    overall_score: Optional[int]
    summary: Optional[str]
    event_count: Optional[dict]
    timeline: Optional[list]
    published_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True

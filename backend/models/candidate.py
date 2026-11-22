# FILE: backend/models/candidate.py
# Pydantic models for Candidate

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class CandidateInvite(BaseModel):
    email: str = Field(..., min_length=1)


class EnrollmentData(BaseModel):
    session_id: UUID
    face_descriptor: List[float] = Field(..., min_length=128, max_length=128)
    photo_base64: Optional[str] = None


class SessionCandidateResponse(BaseModel):
    id: UUID
    session_id: UUID
    candidate_id: UUID
    invite_token: Optional[str]
    enrolled_at: Optional[datetime]
    face_descriptor: Optional[dict]
    joined_at: Optional[datetime]
    left_at: Optional[datetime]

    class Config:
        from_attributes = True


class CandidateProfileResponse(BaseModel):
    id: UUID
    full_name: str
    email: str
    institution: Optional[str]
    avatar_url: Optional[str]

    class Config:
        from_attributes = True

# FILE: backend/models/candidate.py
# Pydantic models for Candidate

from pydantic import BaseModel, Field, AliasChoices
from typing import Optional, List
from datetime import datetime
from uuid import UUID


class CandidateInvite(BaseModel):
    email: str = Field(..., min_length=1)


class EnrollmentData(BaseModel):
    session_id: UUID = Field(..., validation_alias=AliasChoices('session_id', 'sessionId'))
    face_descriptor: List[float] = Field(..., min_length=128, max_length=128, validation_alias=AliasChoices('face_descriptor', 'faceDescriptor'))
    photo_base64: Optional[str] = None


class SessionCandidateResponse(BaseModel):
    id: UUID
    session_id: UUID
    candidate_id: UUID
    invite_token: Optional[str] = None
    enrolled_at: Optional[datetime] = None
    face_descriptor: Optional[List[float]] = None
    joined_at: Optional[datetime] = None
    left_at: Optional[datetime] = None
    full_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None

    class Config:
        from_attributes = True
        extra = "ignore"


class CandidateProfileResponse(BaseModel):
    id: UUID
    full_name: str
    email: str
    institution: Optional[str]
    avatar_url: Optional[str]

    class Config:
        from_attributes = True

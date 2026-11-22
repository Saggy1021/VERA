# FILE: backend/services/storage_service.py
# Upload evidence to Supabase Storage

import base64
import os
from datetime import datetime
from uuid import uuid4

from config import settings

# Use Supabase Storage by default
try:
    from supabase import create_client
    _supabase = None

    def _get_supabase():
        global _supabase
        if _supabase is None and settings.supabase_url and settings.supabase_service_role_key:
            _supabase = create_client(
                settings.supabase_url,
                settings.supabase_service_role_key,
            )
        return _supabase
except ImportError:
    def _get_supabase():
        return None


async def upload_screenshot(
    screenshot_b64: str,
    session_id: str,
    candidate_id: str,
) -> str | None:
    """
    Upload a screenshot to Supabase Storage.
    Returns the public URL of the uploaded file.
    Returns None if storage is not configured or upload fails.
    """
    supabase = _get_supabase()
    if not supabase:
        return None

    try:
        # Decode base64
        image_bytes = base64.b64decode(screenshot_b64)

        # Generate unique filename
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_id = str(uuid4())[:8]
        file_path = f"{session_id}/{candidate_id}/{timestamp}_{file_id}.jpg"

        # Upload to Supabase Storage
        bucket = settings.supabase_storage_bucket
        supabase.storage.from_(bucket).upload(
            file_path,
            image_bytes,
            {"content-type": "image/jpeg"},
        )

        # Get public URL
        url = supabase.storage.from_(bucket).get_public_url(file_path)
        return url
    except Exception:
        return None


async def upload_evidence_clip(
    clip_bytes: bytes,
    session_id: str,
    candidate_id: str,
) -> str | None:
    """
    Upload a WebM evidence clip to Supabase Storage.
    Returns the public URL or None on failure.
    """
    supabase = _get_supabase()
    if not supabase:
        return None

    try:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_id = str(uuid4())[:8]
        file_path = f"{session_id}/{candidate_id}/clips/{timestamp}_{file_id}.webm"

        bucket = settings.supabase_storage_bucket
        supabase.storage.from_(bucket).upload(
            file_path,
            clip_bytes,
            {"content-type": "video/webm"},
        )

        url = supabase.storage.from_(bucket).get_public_url(file_path)
        return url
    except Exception:
        return None


async def upload_clip(
    clip_bytes: bytes,
    session_id: str,
    candidate_id: str,
    event_type: str = "unknown",
    filename: str | None = None,
) -> str | None:
    """
    Upload a 30-second WebM circular buffer clip.
    This is the function called from events.py /api/events/clip.
    event_type and filename are embedded in the storage path for traceability.
    Returns the public URL or None on failure (non-fatal).
    """
    supabase = _get_supabase()
    if not supabase:
        return None

    try:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_id = str(uuid4())[:8]
        safe_event = event_type.replace("/", "_")
        file_path = f"{session_id}/{candidate_id}/clips/{timestamp}_{safe_event}_{file_id}.webm"

        bucket = settings.supabase_storage_bucket
        supabase.storage.from_(bucket).upload(
            file_path,
            clip_bytes,
            {"content-type": "video/webm"},
        )

        url = supabase.storage.from_(bucket).get_public_url(file_path)
        return url
    except Exception:
        return None


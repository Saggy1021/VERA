# FILE: backend/services/storage_service.py
# Upload evidence to Supabase Storage with async thread wrapping

import base64
import asyncio
from datetime import datetime
from uuid import uuid4

from config import settings

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


def _sync_upload_screenshot(screenshot_b64: str, session_id: str, candidate_id: str) -> str | None:
    supabase = _get_supabase()
    if not supabase:
        return None
    try:
        image_bytes = base64.b64decode(screenshot_b64)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        file_id = str(uuid4())[:8]
        file_path = f"{session_id}/{candidate_id}/{timestamp}_{file_id}.jpg"
        bucket = settings.supabase_storage_bucket

        supabase.storage.from_(bucket).upload(
            file_path,
            image_bytes,
            {"content-type": "image/jpeg"},
        )
        return supabase.storage.from_(bucket).get_public_url(file_path)
    except Exception:
        return None


async def upload_screenshot(
    screenshot_b64: str,
    session_id: str,
    candidate_id: str,
) -> str | None:
    """Async non-blocking screenshot upload."""
    return await asyncio.to_thread(_sync_upload_screenshot, screenshot_b64, session_id, candidate_id)


def _sync_upload_clip(clip_bytes: bytes, session_id: str, candidate_id: str, event_type: str = "unknown") -> str | None:
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
        return supabase.storage.from_(bucket).get_public_url(file_path)
    except Exception:
        return None


async def upload_clip(
    clip_bytes: bytes,
    session_id: str,
    candidate_id: str,
    event_type: str = "unknown",
    filename: str | None = None,
) -> str | None:
    """Async non-blocking clip upload."""
    return await asyncio.to_thread(_sync_upload_clip, clip_bytes, session_id, candidate_id, event_type)


async def upload_evidence_clip(
    clip_bytes: bytes,
    session_id: str,
    candidate_id: str,
) -> str | None:
    return await upload_clip(clip_bytes, session_id, candidate_id)

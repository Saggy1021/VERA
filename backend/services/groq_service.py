# FILE: backend/services/groq_service.py
# Groq free tier: whisper-large-v3-turbo, very fast transcription

import httpx
import os
import logging
from typing import Optional
from config import settings

log = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


async def transcribe_audio(
    audio_bytes: bytes,
    client: Optional[httpx.AsyncClient] = None,
    language: str = "en",
) -> Optional[str]:
    """
    Called when speech activity is detected.
    Audio is 16kHz mono WAV chunk.
    Returns transcript string or None cleanly without blocking.
    """
    key = os.environ.get("GROQ_API_KEY") or settings.groq_api_key
    if not key:
        return None  # Transcription is optional enhancement

    headers = {"Authorization": f"Bearer {key}"}
    files = {"file": ("speech.wav", audio_bytes, "audio/wav")}
    data = {"model": "whisper-large-v3-turbo", "language": language}

    try:
        if client:
            resp = await client.post(
                GROQ_API_URL,
                headers=headers,
                files=files,
                data=data,
                timeout=12.0,
            )
            if resp.status_code == 200:
                return resp.json().get("text", "").strip() or None
        else:
            async with httpx.AsyncClient(timeout=12.0) as local_client:
                resp = await local_client.post(
                    GROQ_API_URL,
                    headers=headers,
                    files=files,
                    data=data,
                )
                if resp.status_code == 200:
                    return resp.json().get("text", "").strip() or None
    except Exception as exc:
        log.debug("Groq Whisper transcription exception: %s", exc)
        return None

    return None

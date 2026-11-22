# FILE: backend/services/groq_service.py
# Groq free tier: whisper-large-v3-turbo, very fast transcription

import httpx
import os

GROQ_API_URL = 'https://api.groq.com/openai/v1/audio/transcriptions'
GROQ_API_KEY = os.environ.get('GROQ_API_KEY', '')


async def transcribe_audio(
    audio_bytes: bytes,
    client: httpx.AsyncClient,
    language: str = 'en'
) -> str | None:
    """
    Called ONLY when the audio_worker detects speech activity.
    Audio is 5-second WAV chunks at 16kHz mono.
    """
    if not GROQ_API_KEY:
        return None  # Transcription is optional enhancement

    try:
        resp = await client.post(
            GROQ_API_URL,
            headers={'Authorization': f'Bearer {GROQ_API_KEY}'},
            files={'file': ('audio.wav', audio_bytes, 'audio/wav')},
            data={'model': 'whisper-large-v3-turbo', 'language': language},
            timeout=15.0
        )
        return resp.json().get('text', '').strip() or None
    except Exception:
        return None  # Transcription is optional enhancement — never block on it

# FILE: backend/services/gemini_service.py
# Gemini AI screenshot analysis for HIGH severity proctoring events

import httpx
import os
import json
from config import settings

PROMPT_TEMPLATE = """
You are a professional online exam proctor AI. Analyze this screenshot from a candidate's exam session.
The automated system flagged this image for: {flag_types}.
Respond with a JSON object ONLY, no prose:
{{
  "confirmed": true|false,
  "confidence": 0.0-1.0,
  "observations": "one sentence describing what you see",
  "recommended_action": "none|warn_candidate|flag_for_review|terminate"
}}
"""


async def analyze_screenshot(
    screenshot_b64: str,
    flag_types: list[str],
    client: httpx.AsyncClient | None = None
) -> dict:
    """
    Called asynchronously for HIGH severity events.
    Returns a verdict that is stored in the event record.
    Failure must NEVER crash the event handler.
    """
    api_key = settings.gemini_api_key or os.environ.get('GEMINI_API_KEY', '')
    if not api_key:
        return {'verdict': None, 'status': 'skipped', 'error': 'No API key configured'}

    # Use fast lightweight endpoint
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"
    payload = {
        'contents': [{
            'parts': [
                {'text': PROMPT_TEMPLATE.format(flag_types=', '.join(flag_types))},
                {'inline_data': {'mime_type': 'image/jpeg', 'data': screenshot_b64}}
            ]
        }],
        'generationConfig': {'temperature': 0.1, 'maxOutputTokens': 200}
    }

    try:
        if client:
            resp = await client.post(url, json=payload, timeout=5.0)
        else:
            async with httpx.AsyncClient() as c:
                resp = await c.post(url, json=payload, timeout=5.0)

        if resp.status_code == 200:
            data = resp.json()
            text = data['candidates'][0]['content']['parts'][0]['text']
            return {'verdict': text, 'status': 'ok'}
        else:
            return {'verdict': None, 'status': 'error', 'error': f"HTTP {resp.status_code}"}
    except Exception as e:
        return {'verdict': None, 'status': 'error', 'error': str(e)}

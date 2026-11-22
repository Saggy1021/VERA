# FILE: backend/services/gemini_service.py
# Gemini Flash API: analyze screenshot

import httpx
import os

GEMINI_URL = 'https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent'
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

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
    client: httpx.AsyncClient
) -> dict:
    """
    Called ONLY for HIGH severity events.
    Receives the screenshot and a structured prompt.
    Returns a verdict that is stored in the event record.
    """
    if not GEMINI_API_KEY:
        return {'verdict': None, 'status': 'skipped', 'error': 'No API key configured'}

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
        resp = await client.post(
            GEMINI_URL,
            params={'key': GEMINI_API_KEY},
            json=payload,
            timeout=8.0
        )
        text = resp.json()['candidates'][0]['content']['parts'][0]['text']
        return {'verdict': text, 'status': 'ok'}
    except Exception as e:
        return {'verdict': None, 'status': 'error', 'error': str(e)}
        # IMPORTANT: Gemini failure must NEVER crash the event handler.
        # The event is still saved without a Gemini verdict.

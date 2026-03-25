"""
VERA — FastAPI backend (Production v2)
Endpoints:
  GET  /                       — Dashboard HTML
  WS   /ws/analyze/{session}   — Real-time frame analysis
  POST /analyze/video          — Upload & analyse an entire video
  GET  /report/{session}       — Fetch session report JSON
"""
import asyncio
import base64
import io
import json
import os
import sys
import tempfile
import time
import uuid
from typing import Dict

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── Path setup ────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="VERA — Visual Expression & Response Analyzer", version="2.0")

# Serve static assets (CSS / JS)
_static = os.path.join(BASE, "static")
if os.path.isdir(_static):
    app.mount("/static", StaticFiles(directory=_static), name="static")

# Session store  {session_id: {"pipeline": VERAPipeline, "results": [...], ...}}
_sessions: Dict[str, dict] = {}

# Pipeline factory — lazy-imported so TF loads once
_pipeline_cls = None

def _get_pipeline_cls():
    global _pipeline_cls
    if _pipeline_cls is None:
        sys.path.insert(0, BASE)
        from vera.vera_pipeline import VERAPipeline
        _pipeline_cls = VERAPipeline
    return _pipeline_cls


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    tpl = os.path.join(BASE, "templates", "index.html")
    with open(tpl, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.websocket("/ws/analyze/{session_id}")
async def websocket_analyze(websocket: WebSocket, session_id: str):
    await websocket.accept()
    print(f"[WS] Session {session_id} connected.")

    # Create / reuse pipeline for session
    if session_id not in _sessions:
        context = "interview"
        P = _get_pipeline_cls()
        pipeline = P(context=context, use_lipnet=True)
        _sessions[session_id] = {
            "pipeline": pipeline,
            "results":  [],
            "start":    time.time(),
            "context":  context,
        }
    sess = _sessions[session_id]
    pipeline: object = sess["pipeline"]

    try:
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            msg = json.loads(raw)

            # ── Frame analysis ────────────────────────────────────────────
            if msg.get("type") == "frame":
                img_b64 = msg["data"].split(",")[-1]          # strip data-URI prefix
                img_bytes = base64.b64decode(img_b64)
                npa  = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(npa, cv2.IMREAD_COLOR)
                if frame is None:
                    await websocket.send_text(json.dumps({"error": "Bad frame"}))
                    continue

                # Resize to max 640-wide for speed
                h, w = frame.shape[:2]
                if w > 640:
                    scale = 640 / w
                    frame = cv2.resize(frame, (640, int(h * scale)))

                result = pipeline.process_frame(frame, has_audio=False)

                # Build annotated JPEG for display
                _, buf = cv2.imencode(".jpg", result["annotated_frame"],
                                      [cv2.IMWRITE_JPEG_QUALITY, 75])
                ann_b64 = base64.b64encode(buf).decode()

                payload = _build_payload(result, ann_b64)
                sess["results"].append({
                    "ts":       time.time(),
                    "deception":result["deception"]["score"],
                    "emotion":  result["emotion"].get("label"),
                    "gaze":     result["behavior"]["gaze"]["direction"],
                })
                await websocket.send_text(json.dumps(payload))

            # ── Audio text update ─────────────────────────────────────────
            elif msg.get("type") == "audio_text":
                pipeline.set_audio_text(msg.get("text", ""))
                await websocket.send_text(json.dumps({"type": "ack_audio"}))

            # ── Ping ──────────────────────────────────────────────────────
            elif msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        print(f"[WS] Session {session_id} disconnected.")
    except asyncio.TimeoutError:
        print(f"[WS] Session {session_id} timed-out.")
    except Exception as exc:
        print(f"[WS] Error in session {session_id}: {exc}")
        try:
            await websocket.send_text(json.dumps({"error": str(exc)}))
        except Exception:
            pass


@app.post("/analyze/video")
async def analyze_video(
    file: UploadFile = File(...),
    context: str = Form(default="interview"),
):
    """Upload a video file and return a full analysis report."""
    session_id = str(uuid.uuid4())
    suffix = os.path.splitext(file.filename)[-1] or ".mp4"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(await file.read())
        tmp_path = tmp.name

    out_path = tmp_path.replace(suffix, "_annotated.mp4")

    P = _get_pipeline_cls()
    pipeline = P(context=context, use_lipnet=True)
    report = pipeline.analyze_video_file(tmp_path, output_path=out_path)

    _sessions[session_id] = {
        "pipeline": pipeline,
        "results":  report.get("frames", []),
        "start":    time.time(),
        "context":  context,
        "report":   report.get("summary", {}),
    }

    try:
        os.unlink(tmp_path)
    except Exception:
        pass

    return JSONResponse({
        "session_id":   session_id,
        "summary":      report.get("summary", {}),
        "frame_count":  len(report.get("frames", [])),
        "has_annotated":os.path.exists(out_path),
    })


@app.get("/report/{session_id}")
async def get_report(session_id: str):
    sess = _sessions.get(session_id)
    if not sess:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    summary = sess.get("report")
    if summary is None and sess.get("pipeline"):
        summary = sess["pipeline"].deception.get_session_summary()
    return JSONResponse({"session_id": session_id, "summary": summary,
                         "results": sess["results"][-200:]})


@app.get("/health")
async def health():
    return {"status": "ok", "sessions": len(_sessions)}


# ── Helper ────────────────────────────────────────────────────────────────────
def _build_payload(result: dict, ann_b64: str) -> dict:
    """Flatten result dict into a JSON-safe payload for the browser."""
    emo = result["emotion"]
    beh = result["behavior"]
    dec = result["deception"]
    syn = result["sync"]

    # Strip non-serialisable objects
    beh_clean = {
        k: v for k, v in beh.items()
        if k not in ("landmarks", "frame_shape")
    }
    # gaze_interpretation is already a plain dict
    for sub in ("gaze", "blink", "head_pose", "eye_contact",
                "gaze_interpretation"):
        if sub in beh_clean:
            beh_clean[sub] = dict(beh_clean[sub]) if hasattr(beh_clean[sub], "items") else beh_clean[sub]

    return {
        "type":           "result",
        "frame_id":       result["frame_id"],
        "processing_ms":  result["processing_ms"],
        "annotated":      f"data:image/jpeg;base64,{ann_b64}",
        "emotion": {
            "label":      emo.get("label"),
            "confidence": emo.get("confidence"),
            "dominant":   emo.get("dominant"),
            "all":        emo.get("all", {}),
            "risk_score": emo.get("risk_score"),
            "is_deceptive":emo.get("is_deceptive_emotion"),
            "color":      list(emo.get("color", [255, 255, 255])),
        },
        "behavior":       beh_clean,
        "deception": {
            "score":          dec["score"],
            "verdict":        dec["verdict"],
            "level":          dec["level"],
            "flags":          dec["flags"],
            "running_average":dec["running_average"],
            "all_signals":    dec["all_signals"],
        },
        "sync": {
            "score":     syn.get("score"),
            "is_synced": syn.get("is_synced"),
            "verdict":   syn.get("verdict"),
        },
        "lip_text":       result["lip_text"],
        "lip_movement":   result["lip_movement"],
        "mouth_open":     result["mouth_open"],
        "alerts":         result["alerts"],
    }

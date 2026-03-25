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
import math
import os
import sys
import tempfile
import time
import uuid
from typing import Dict

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ── VERA module imports ───────────────────────────────────────────────────────
from vera.audit_logger import AuditLogger
from vera.consent_manager import ConsentManager
from vera.session_recorder import SessionRecorder
from vera.identity_verifier import IdentityVerifier

# ── Path setup ────────────────────────────────────────────────────────────────
BASE = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="VERA — Visual Expression & Response Analyzer", version="2.0")

# Allow all origins so the dashboard works on localhost, LAN IP, and ngrok tunnels
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Serve static assets (CSS / JS)
_static = os.path.join(BASE, "static")
if os.path.isdir(_static):
    app.mount("/static", StaticFiles(directory=_static), name="static")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    ico = os.path.join(BASE, "static", "favicon.ico")
    if os.path.exists(ico):
        return FileResponse(ico)
    from fastapi.responses import Response
    return Response(status_code=204)

# Session store  {session_id: {"pipeline": VERAPipeline, "results": [...], ...}}
_sessions: Dict[str, dict] = {}

# Shared singletons
audit_logger = AuditLogger()
consent_manager = ConsentManager()

@app.on_event("startup")
async def startup():
    await audit_logger.initialize()
    # Warm up heavy singletons so first WebSocket connection is fast
    loop = asyncio.get_running_loop()

    def _warmup():
        try:
            P = _get_pipeline_cls()
            # Instantiating once warms up all singletons:
            # AudioAnalyzer (Whisper), MultiFaceDetector (InsightFace det)
            _ = P(context="interview")
            print("[VERA] Startup warmup complete — singletons ready.")
        except Exception as exc:
            print(f"[VERA] Startup warmup warning: {exc}")

    await loop.run_in_executor(None, _warmup)

# Pipeline factory — lazy-imported so TF loads once
_pipeline_cls = None

def _get_pipeline_cls():
    global _pipeline_cls
    if _pipeline_cls is None:
        sys.path.insert(0, BASE)
        from vera.vera_pipeline import VERAPipeline
        _pipeline_cls = VERAPipeline
    return _pipeline_cls


# ── JSON safety ───────────────────────────────────────────────────────────────
# Grab numpy scalar base classes once so isinstance checks are fast.
try:
    import numpy as _np
    _NP_BOOL     = _np.bool_
    _NP_INTEGER  = _np.integer
    _NP_FLOATING = _np.floating
    _NP_NDARRAY  = _np.ndarray
except ImportError:
    _NP_BOOL = _NP_INTEGER = _NP_FLOATING = _NP_NDARRAY = type(None)

def _sanitise(v):
    """Recursively convert numpy scalars / NaN / Inf into JSON-safe Python types.
    numpy.bool_, numpy.float64, numpy.int64 are NOT JSON-serialisable by default
    and will crash json.dumps the moment a face is detected.
    """
    # numpy scalars — check BEFORE plain Python float/int (they don't inherit from them)
    if isinstance(v, _NP_BOOL):
        return bool(v)
    if isinstance(v, _NP_INTEGER):
        return int(v)
    if isinstance(v, _NP_FLOATING):
        f = float(v)
        return 0.0 if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(v, _NP_NDARRAY):
        return [_sanitise(i) for i in v.tolist()]
    # plain Python types
    if isinstance(v, float):
        return 0.0 if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, dict):
        return {k: _sanitise(val) for k, val in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitise(i) for i in v]
    return v


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def landing():
    tpl = os.path.join(BASE, "templates", "landing.html")
    with open(tpl, encoding="utf-8") as f:
        return HTMLResponse(f.read())


def _serve_template(name: str):
    tpl = os.path.join(BASE, "templates", name)
    with open(tpl, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/setup", response_class=HTMLResponse)
async def setup_page():
    return _serve_template("setup.html")


@app.get("/interview", response_class=HTMLResponse)
async def interview_page():
    return _serve_template("interview.html")


@app.get("/exam", response_class=HTMLResponse)
async def exam_page():
    return _serve_template("exam.html")


@app.get("/review", response_class=HTMLResponse)
async def review_page():
    return _serve_template("review.html")


@app.get("/report-page", response_class=HTMLResponse)
async def report_page():
    return _serve_template("report.html")


# ── Consent API ───────────────────────────────────────────────────────────────
@app.post("/api/consent")
async def api_consent(request: Request):
    body = await request.json()
    session_id = body.get("session_id", str(uuid.uuid4()))
    candidate_id = body.get("candidate_id", "unknown")
    given = body.get("consent", False)

    if not consent_manager.is_consent_given(session_id):
        consent_manager.create_consent_request(session_id, candidate_id)

    result = consent_manager.record_consent(
        session_id, given,
        ip_address=request.client.host if request.client else None
    )
    if given:
        await audit_logger.log_session_start(session_id, candidate_id, body.get("exam_id", ""), given)
    return JSONResponse(result)


# ── Identity Enrollment API ───────────────────────────────────────────────────
@app.post("/api/enroll")
async def api_enroll(request: Request):
    body = await request.json()
    session_id = body.get("session_id", "")
    img_b64 = body.get("image", "").split(",")[-1]
    if not img_b64:
        return JSONResponse({"success": False, "message": "No image data."}, status_code=400)

    img_bytes = base64.b64decode(img_b64)
    npa = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(npa, cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse({"success": False, "message": "Invalid image."}, status_code=400)

    sess = _sessions.get(session_id)
    if sess and sess.get("pipeline"):
        result = sess["pipeline"].identity.enroll(frame)
    else:
        verifier = IdentityVerifier()
        result = verifier.enroll(frame)
    return JSONResponse(result)


# ── Face Check API (for pre-session setup) ──────────────────────────────────
_mfd = None
def _get_mfd():
    global _mfd
    if _mfd is None:
        from vera.multi_face_detector import MultiFaceDetector
        _mfd = MultiFaceDetector()
    return _mfd

@app.post("/api/face_check")
async def api_face_check(request: Request):
    body = await request.json()
    img_b64 = body.get("image", "").split(",")[-1]
    if not img_b64:
        return JSONResponse({"success": False, "message": "No image data."}, status_code=400)

    img_bytes = base64.b64decode(img_b64)
    npa = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(npa, cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse({"success": False, "message": "Invalid image."}, status_code=400)
    
    mfd = _get_mfd()
    result = mfd.detect(frame)
    if result["face_count"] > 0:
        return JSONResponse({"success": True, "face_detected": True, "face_count": result["face_count"]})
    return JSONResponse({"success": False, "face_detected": False, "message": "No face detected in frame."})


# ── Environment Scan API (for pre-session setup) ────────────────────────────
_env_det = None
def _get_env_det():
    global _env_det
    if _env_det is None:
        from vera.environment_detector import EnvironmentDetector
        _env_det = EnvironmentDetector()
    return _env_det

@app.post("/api/env_scan")
async def api_env_scan(request: Request):
    body = await request.json()
    img_b64 = body.get("image", "").split(",")[-1]
    if not img_b64:
        return JSONResponse({"success": False, "message": "No image data."}, status_code=400)

    img_bytes = base64.b64decode(img_b64)
    npa = np.frombuffer(img_bytes, np.uint8)
    frame = cv2.imdecode(npa, cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse({"success": False, "message": "Invalid image."}, status_code=400)
    
    env_det = _get_env_det()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, env_det.analyze, frame)
    return JSONResponse({"success": True, "environment": _sanitise(result)})


# ── Session List API (for review page) ────────────────────────────────────────
@app.get("/api/sessions")
async def api_sessions(severity: str = None):
    sessions_list = []
    for sid, sess in _sessions.items():
        info = {
            "session_id": sid,
            "context": sess.get("context", "unknown"),
            "start": sess.get("start", 0),
            "result_count": len(sess.get("results", [])),
        }
        if sess.get("pipeline"):
            current = sess["pipeline"].deception.get_current()
            info["risk_score"] = current["risk_score"]
            info["severity"] = current["severity"]
        sessions_list.append(info)

    if severity:
        sessions_list = [s for s in sessions_list if s.get("severity") == severity.upper()]
    return JSONResponse(sessions_list)


@app.post("/api/analyze_video")
async def analyze_video_upload(file: UploadFile = File(...)):
    """
    Demo mode video upload endpoint.
    Accepts a video file, runs full VERA pipeline analysis, returns summary.
    Delegates to the thread-safe analyze_video_file() method.
    """
    import tempfile as _tmpmod

    suffix = os.path.splitext(file.filename or "")[1] or ".mp4"
    tmp_fd, tmp_path = _tmpmod.mkstemp(suffix=suffix, prefix="vera_demo_")

    try:
        # Write uploaded bytes to temp file
        with os.fdopen(tmp_fd, "wb") as fh:
            while True:
                chunk = await file.read(1024 * 1024)  # 1 MB chunks
                if not chunk:
                    break
                fh.write(chunk)

        # Run blocking analysis off the event loop
        def _run():
            P = _get_pipeline_cls()
            pipeline = P(context="demo")
            return pipeline.analyze_video_file(tmp_path)

        loop = asyncio.get_running_loop()
        raw = await loop.run_in_executor(None, _run)

        # analyze_video_file returns {"summary": {...}, "frames": [...]} 
        summary = raw.get("summary", {})

        return JSONResponse({
            "final_score":  round(float(summary.get("final_score", 0.0)), 2),
            "severity":     summary.get("severity", "CLEAN"),
            "risk_score":   round(float(summary.get("final_score", 0.0)), 2),
            "flags":        summary.get("active_flags", []),
            "transcript":   summary.get("audio_transcription", ""),
            "frame_count":  summary.get("total_frames", 0),
            "alerts":       summary.get("alerts", []),
            "emotion_distribution": summary.get("emotion_distribution", {}),
        })

    except Exception as exc:
        import logging, traceback
        logging.getLogger(__name__).error(
            "analyze_video_upload error: %s\n%s", exc, traceback.format_exc()
        )
        return JSONResponse({"error": str(exc)}, status_code=500)

    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


@app.websocket("/ws/analyze/{session_id}")
async def websocket_analyze(websocket: WebSocket, session_id: str,
                             context: str = Query(default="interview")):
    await websocket.accept()
    print(f"[WS] Session {session_id} connected (context={context}).")

    # Create / reuse pipeline for session
    # Evict sessions idle for more than 30 minutes to prevent unbounded RAM growth
    _cutoff = time.time() - 1800
    stale = [sid for sid, s in list(_sessions.items()) if s.get("last_active", 0) < _cutoff]
    for sid in stale:
        print(f"[WS] Evicting stale session {sid}")
        _sessions.pop(sid, None)

    if session_id not in _sessions:
        P = _get_pipeline_cls()
        pipeline = P(context=context)
        _sessions[session_id] = {
            "pipeline":    pipeline,
            "recorder":    SessionRecorder(session_id),
            "results":     [],
            "start":       time.time(),
            "last_active": time.time(),
            "context":     context,
            "audio_buf":   bytearray(),
            "chunk_count": 0,
            "pending_security_flags": {},
        }
    sess = _sessions[session_id]
    pipeline: object = sess["pipeline"]
    recorder = sess.get("recorder")

    try:
        while True:
            raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
            msg = json.loads(raw)

            # ── Consent gate ──────────────────────────────────────────────
            if msg.get("type") == "consent":
                body = msg.get("data", {})
                candidate_id = body.get("candidate_id", "unknown")
                given = body.get("consent", False)
                consent_manager.create_consent_request(session_id, candidate_id)
                result = consent_manager.record_consent(session_id, given)
                if given:
                    await audit_logger.log_session_start(
                        session_id, candidate_id, body.get("exam_id", ""), given
                    )
                await websocket.send_text(json.dumps({"type": "consent_ack", **result}))
                continue

            # ── Frame analysis ────────────────────────────────────────────
            if msg.get("type") == "frame":
                # Security events can arrive as frame messages without image data.
                # Queue these flags and merge into the next real frame.
                security_flags = dict(msg.get("security_flags") or {})
                frame_data = msg.get("data", "")

                if not frame_data:
                    if security_flags:
                        pending = sess.get("pending_security_flags", {})
                        pending.update(security_flags)
                        sess["pending_security_flags"] = pending
                    await websocket.send_text(json.dumps({
                        "type": "frame_error",
                        "error": "Empty frame payload"
                    }))
                    continue

                img_b64 = frame_data.split(",")[-1]          # strip data-URI prefix
                try:
                    img_bytes = base64.b64decode(img_b64)
                except Exception:
                    await websocket.send_text(json.dumps({
                        "type": "frame_error",
                        "error": "Invalid frame encoding"
                    }))
                    continue

                npa  = np.frombuffer(img_bytes, np.uint8)
                frame = cv2.imdecode(npa, cv2.IMREAD_COLOR)
                if frame is None:
                    await websocket.send_text(json.dumps({
                        "type": "frame_error",
                        "error": "Bad frame"
                    }))
                    continue

                # Resize to max 480-wide for faster processing
                h, w = frame.shape[:2]
                if w > 480:
                    scale = 480 / w
                    frame = cv2.resize(frame, (480, int(h * scale)))

                # Run heavy inference in a thread pool so the asyncio event loop
                # stays alive for heartbeats, pings and concurrent WebSocket sessions.
                # has_audio must reflect whether we actually have transcribed speech
                # so the AV-mismatch and silent-mouthing signals can fire.
                pending_flags = sess.get("pending_security_flags", {})
                if pending_flags:
                    security_flags = {**pending_flags, **security_flags}
                    sess["pending_security_flags"] = {}
                loop = asyncio.get_running_loop()
                has_audio = bool(getattr(pipeline, "has_recent_audio_activity", lambda *_: False)(5.0))
                try:
                    result = await loop.run_in_executor(
                        None, lambda f=frame, ha=has_audio, sf=security_flags: pipeline.process_frame(f, ha, sf)
                    )
                except Exception as frame_exc:
                    import traceback
                    print(f"[WS] Frame processing error: {frame_exc}")
                    traceback.print_exc()
                    await websocket.send_text(json.dumps({
                        "type": "frame_error",
                        "error": str(frame_exc)
                    }))
                    continue

                # Update session activity timestamp
                sess["last_active"] = time.time()

                # Add frame to evidence buffer
                if recorder:
                    recorder.add_frame(frame)

                # Audit log HIGH severity flags
                dec = result.get("deception", {})
                if dec.get("level") == "high":
                    evidence_key = None
                    if recorder:
                        evidence_key = recorder.extract_evidence_clip("high_risk")
                    await audit_logger.log_event(
                        session_id, "HIGH_RISK",
                        dec.get("level", "high"),
                        dec.get("score", 0),
                        {"flags": dec.get("flags", [])},
                        evidence_key
                    )

                # Skip expensive annotated frame encoding — browser shows raw camera
                payload = _build_payload(result, "")
                payload = _sanitise(payload)
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
            # ── Live audio chunk (webm/opus from MediaRecorder) ──────────
            elif msg.get("type") == "audio_chunk":
                chunk_b64 = msg.get("data", "")
                if chunk_b64:
                    try:
                        chunk_bytes = base64.b64decode(chunk_b64.split(",")[-1])
                    except Exception:
                        await websocket.send_text(json.dumps({
                            "type": "ack_audio",
                            "text": "",
                            "sync": dict(getattr(pipeline, "_latest_sync", {}) or {}),
                            "error": "Invalid audio chunk encoding",
                        }))
                        continue
                    sess["chunk_count"] = sess.get("chunk_count", 0) + 1
                    # MediaRecorder emits time-sliced chunks. Keep a low minimum
                    # size so quieter speech still gets transcribed.
                    if len(chunk_bytes) > 1200:
                        audio_data = bytes(chunk_bytes)
                        def _transcribe_live(data=audio_data, pipe=pipeline):
                            import tempfile as _tf
                            with _tf.NamedTemporaryFile(suffix=".webm", delete=False) as tf:
                                tf.write(data); tmp = tf.name
                            try:
                                tr   = pipe.audio.transcribe_file(tmp)
                                energy = pipe.audio.compute_energy(tmp)
                                text = tr.get("text", "")
                                has_speech = bool(text)
                                err = tr.get("error")
                                pipe.update_audio_activity(energy=energy, has_speech=has_speech)
                                if text:
                                    pipe.set_audio_text(text)
                                return text, pipe._latest_sync, energy, err
                            finally:
                                try: os.unlink(tmp)
                                except: pass
                        loop2 = asyncio.get_running_loop()
                        text, sync, energy, tr_error = await loop2.run_in_executor(None, _transcribe_live)
                        
                        # Audio Anomaly alert trigger
                        if energy > 10.0:
                            ts = time.strftime("%H:%M:%S")
                            if not any("Audio Anomaly" in a["msg"] for a in pipeline._alerts[-4:]):
                                pipeline._alerts.append({"time": ts, "msg": f"🗣️ Audio Anomaly: Talking/Noise detected (Energy: {energy})"})

                        await websocket.send_text(json.dumps({
                            "type": "ack_audio",
                            "text": text,
                            "sync": sync if sync else {},
                            "error": tr_error,
                        }))
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
    finally:
        # Session cleanup
        if session_id in _sessions:
            sess = _sessions[session_id]
            p = sess.get("pipeline")
            if p:
                # ── CRITICAL ORDER ────────────────────────────────────────
                # 1. Save the final summary into sess["report"] BEFORE reset.
                #    The report page fetches /report/{session_id} AFTER this
                #    finally block runs. If we reset first, the report is blank.
                # 2. Compute current state for audit log.
                # 3. Reset scorer LAST — after saving.
                try:
                    sess["report"] = p.get_session_summary()
                except Exception as _e:
                    print(f"[WS] Warning: could not save session summary: {_e}")
                    sess["report"] = {}

                current = p.deception.get_current()
                await audit_logger.log_session_end(
                    session_id,
                    current['risk_score'],
                    current['severity']
                )
                # Reset scorer last — report is already saved above
                p.deception.reset()

            r = sess.get("recorder")
            if r:
                r.reset()
            consent_manager.cleanup(session_id)
            # DO NOT pop session from _sessions here — report page needs it.
            # Sessions are evicted after 30 min idle by the eviction logic
            # at the top of websocket_analyze().


@app.post("/analyze/video")
async def analyze_video(
    file: UploadFile = File(...),
    context: str = Form(default="interview"),
):
    """Upload a video file and return a full analysis report.
    Runs CPU-heavy analysis in a thread executor so the event loop stays free.
    """
    session_id = str(uuid.uuid4())
    suffix = os.path.splitext(file.filename or "")[-1] or ".mp4"

    # Stream file to disk in chunks to support large uploads
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        while True:
            chunk = await file.read(1024 * 1024)  # 1 MB chunks
            if not chunk:
                break
            tmp.write(chunk)
        tmp_path = tmp.name

    out_path = tmp_path.replace(suffix, "_annotated.mp4")

    def _run_analysis():
        P = _get_pipeline_cls()
        pipeline = P(context=context)
        report = pipeline.analyze_video_file(tmp_path, output_path=out_path)
        return pipeline, report

    # Run blocking analysis off the event loop so WebSocket connections stay alive
    loop = asyncio.get_event_loop()
    try:
        pipeline, report = await loop.run_in_executor(None, _run_analysis)
    except Exception as exc:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        return JSONResponse({"error": str(exc)}, status_code=500)

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

    # Use saved report if available (set in finally block), else compute live
    summary = sess.get("report")
    if not summary and sess.get("pipeline"):
        summary = sess["pipeline"].get_session_summary()
    if not summary:
        summary = {}

    # Aggregate per-frame results for charts
    frame_results = sess.get("results", [])
    emotion_counts = {}
    gaze_counts = {}
    deception_trend = []
    for r in frame_results:
        emo = r.get("emotion")
        if emo:
            emotion_counts[emo] = emotion_counts.get(emo, 0) + 1
        gaze = r.get("gaze")
        if gaze:
            gaze_counts[gaze] = gaze_counts.get(gaze, 0) + 1
        dec = r.get("deception")
        if dec is not None:
            try:
                deception_trend.append(round(float(dec), 1))
            except (TypeError, ValueError):
                pass

    # Inject aggregated stats
    summary = dict(summary)
    summary["emotion_distribution"] = emotion_counts
    summary["gaze_distribution"]    = gaze_counts
    summary["deception_trend"]      = deception_trend[-100:]
    summary["total_frames"]         = len(frame_results)
    summary["session_duration_s"]   = round(time.time() - sess.get("start", time.time()), 0)
    summary["context"]              = sess.get("context", "interview")

    return JSONResponse(_sanitise({
        "session_id": session_id,
        "summary":    summary,
        "results":    frame_results[-200:],
    }))


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
        "perf":           result.get("perf", {}),
        "annotated":      f"data:image/jpeg;base64,{ann_b64}",
        "emotion": {
            "label":               emo.get("label"),
            "confidence":          emo.get("confidence"),
            "dominant":            emo.get("dominant"),
            "scores":              emo.get("scores", {}),
            "risk_score":          emo.get("risk_score"),
            "is_deceptive_emotion":emo.get("is_deceptive_emotion"),
            "micro_expression":    emo.get("micro_expression", False),
            "color":               list(emo.get("color", [255, 255, 255])),
        },
        "behavior":       beh_clean,
        "deception": {
            "score":          dec["score"],
            "verdict":        dec["verdict"],
            "level":          dec["level"],
            "flags":          dec["flags"],
            "running_average":dec["running_average"],
            "all_signals":    dec["all_signals"],
            "cooc_active":    dec.get("cooc_active", 0),
            "cooc_bonus":     dec.get("cooc_bonus",  0.0),
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
        "exam_flags":     result.get("exam_flags", {}),
    }

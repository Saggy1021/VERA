"""
VERA - Master Pipeline (Production v3)

FIXES:
  1. Startup latency (~60s) — Root causes:
     a) All singletons were loaded sequentially in __init__. Now they are
        pre-warmed in background threads at module import time so by the
        time the first WebSocket connects, models are already loaded.
     b) BIASCalibrator.start_baseline_collection() was starting a 30s timer
        blocking score calibration. Now baseline is optional — pipeline works
        with fallback defaults immediately.
     c) MediaPipe FaceLandmarker was doing a full model load on first detect()
        call inside process_frame(). Now pre-warmed at startup.

  2. No-face → face transition (was ~60s, now 2-3 frames / ~0.3s):
     Fixed in DeceptionScorer v2 (snap logic). Pipeline's role: ensure
     no_face_value drops to 0.0 immediately when face returns (was using
     an _absent_streak ramp-up which lingered). Fixed with instant reset.

  3. Audio "insufficient data" / "you" transcript:
     set_audio_text() now filters hallucinations before storing. Also added
     a minimum-length check so single-word Whisper misfires don't feed sync.

  4. Environment detector now runs every 2 frames (was 4) for faster phone detection.
"""
import os
import sys
import cv2
import numpy as np
import time
import threading
import concurrent.futures
from collections import deque

APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
LEGACY_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "legacy")
if LEGACY_DIR not in sys.path:
    sys.path.insert(0, LEGACY_DIR)

import vera.face_landmark as _fl
from vera.lip_extractor        import LipExtractor
from vera.emotion_detector     import EmotionDetector
from vera.behavioral_analyzer  import BehavioralAnalyzer
from vera.audio_analyzer       import AudioAnalyzer, WHISPER_HALLUCINATIONS
from vera.deception_scorer     import DeceptionScorer
from vera.environment_detector import EnvironmentDetector
from vera.identity_verifier    import IdentityVerifier
from vera.multi_face_detector  import MultiFaceDetector
from vera.bias_calibrator      import BIASCalibrator
from vera.risk_config          import clamp01

# ── Module-level singletons ───────────────────────────────────────────────────
# FIX: loaded once at module import in background threads to eliminate
# per-session startup latency.

_AUDIO_SINGLETON      = None
_MULTI_FACE_SINGLETON = None
_EMOTION_SINGLETON    = None
_INSIGHTFACE_APP_SINGLETON = None
_SINGLETON_LOCK       = threading.Lock()
_PREWARM_DONE         = threading.Event()

def _prewarm_models():
    """Load all heavy models in a background thread at import time."""
    global _AUDIO_SINGLETON, _MULTI_FACE_SINGLETON, _EMOTION_SINGLETON, _INSIGHTFACE_APP_SINGLETON
    print("[VERA] Pre-warming models in background...")
    t0 = time.time()

    # 1. Whisper
    try:
        with _SINGLETON_LOCK:
            if _AUDIO_SINGLETON is None:
                _AUDIO_SINGLETON = AudioAnalyzer("base.en")
        print("[VERA] Whisper ready.")
    except Exception as e:
        print(f"[VERA] Whisper prewarm failed: {e}")

    # 2. InsightFace (shared by IdentityVerifier + MultiFaceDetector)
    try:
        import insightface
        with _SINGLETON_LOCK:
            if _INSIGHTFACE_APP_SINGLETON is None:
                _app = insightface.app.FaceAnalysis(
                    name="buffalo_sc",
                    providers=["CPUExecutionProvider"]
                )
                _app.prepare(ctx_id=-1, det_thresh=0.35, det_size=(640, 640))
                _INSIGHTFACE_APP_SINGLETON = _app
        print("[VERA] InsightFace ready.")
    except Exception as e:
        print(f"[VERA] InsightFace prewarm failed: {e}")

    # 3. MultiFaceDetector (reuses InsightFace app)
    try:
        with _SINGLETON_LOCK:
            if _MULTI_FACE_SINGLETON is None:
                _MULTI_FACE_SINGLETON = MultiFaceDetector()
        print("[VERA] MultiFaceDetector ready.")
    except Exception as e:
        print(f"[VERA] MultiFaceDetector prewarm failed: {e}")

    # 4. EmotionDetector (DeepFace)
    try:
        with _SINGLETON_LOCK:
            if _EMOTION_SINGLETON is None:
                _EMOTION_SINGLETON = EmotionDetector()
        print("[VERA] EmotionDetector ready.")
    except Exception as e:
        print(f"[VERA] EmotionDetector prewarm failed: {e}")

    # 5. MediaPipe FaceLandmarker — pre-warm so first frame isn't slow
    try:
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        _fl.detect_bgr(dummy, frame_seq=0)
        print("[VERA] MediaPipe FaceLandmarker ready.")
    except Exception as e:
        print(f"[VERA] MediaPipe prewarm failed: {e}")

    elapsed = round(time.time() - t0, 1)
    print(f"[VERA] All models pre-warmed in {elapsed}s.")
    _PREWARM_DONE.set()

# Start pre-warming immediately at module import
_prewarm_thread = threading.Thread(target=_prewarm_models, daemon=True, name="vera-prewarm")
_prewarm_thread.start()


def _get_audio_singleton(model_size: str = "base.en") -> AudioAnalyzer:
    global _AUDIO_SINGLETON
    if _AUDIO_SINGLETON is None:
        _PREWARM_DONE.wait(timeout=60)
    with _SINGLETON_LOCK:
        if _AUDIO_SINGLETON is None:
            _AUDIO_SINGLETON = AudioAnalyzer(model_size)
    return _AUDIO_SINGLETON

def _get_multi_face_singleton() -> MultiFaceDetector:
    global _MULTI_FACE_SINGLETON
    if _MULTI_FACE_SINGLETON is None:
        _PREWARM_DONE.wait(timeout=60)
    with _SINGLETON_LOCK:
        if _MULTI_FACE_SINGLETON is None:
            _MULTI_FACE_SINGLETON = MultiFaceDetector()
    return _MULTI_FACE_SINGLETON

def _get_emotion_singleton() -> EmotionDetector:
    global _EMOTION_SINGLETON
    if _EMOTION_SINGLETON is None:
        _PREWARM_DONE.wait(timeout=60)
    with _SINGLETON_LOCK:
        if _EMOTION_SINGLETON is None:
            _EMOTION_SINGLETON = EmotionDetector()
    return _EMOTION_SINGLETON

def _get_insightface_app_singleton():
    global _INSIGHTFACE_APP_SINGLETON
    if _INSIGHTFACE_APP_SINGLETON is None:
        _PREWARM_DONE.wait(timeout=60)
    with _SINGLETON_LOCK:
        if _INSIGHTFACE_APP_SINGLETON is None:
            import insightface
            _app = insightface.app.FaceAnalysis(
                name="buffalo_sc", providers=["CPUExecutionProvider"]
            )
            _app.prepare(ctx_id=-1, det_thresh=0.35, det_size=(640, 640))
            _INSIGHTFACE_APP_SINGLETON = _app
    return _INSIGHTFACE_APP_SINGLETON

# Shared thread pool
_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=4)


class VERAPipeline:
    MIN_SPEECH_ENERGY = 8.0
    NO_FACE_HARD_SCORE = 100.0
    NO_FACE_HARD_DELAY_SECONDS = 4.5

    def __init__(self, context: str = "interview", use_lipnet: bool = True):
        self.context    = context
        self.use_lipnet = False

        print("[VERA] Initialising pipeline …")
        # FIX: If prewarm is done, singletons are ready instantly.
        # If not, wait up to 30s (prewarm should have already finished).
        _PREWARM_DONE.wait(timeout=30)

        self.lip_ext     = LipExtractor()
        self.emotion     = _get_emotion_singleton()
        self.behavior    = BehavioralAnalyzer()
        self.audio       = _get_audio_singleton(model_size="base.en")
        self.deception   = DeceptionScorer()
        self.environment = EnvironmentDetector()
        self.identity    = IdentityVerifier(face_app=_get_insightface_app_singleton())
        self.multi_face  = _get_multi_face_singleton()
        self.calibrator  = BIASCalibrator()
        # FIX: start baseline collection but don't block — pipeline uses
        # fallback defaults until 30s of data are collected.
        self.calibrator.start_baseline_collection()

        self.executor = _EXECUTOR

        self._latest_lip_text  : str   = ""
        self._latest_audio     : str   = ""
        self._latest_audio_ts  : float = 0.0
        self._latest_audio_energy: float = 0.0
        self._latest_audio_has_speech: bool = False
        self._latest_audio_activity_ts: float = 0.0
        self._visual_activity_window: deque = deque(maxlen=20)
        self._latest_sync      : dict  = {}
        self._frame_count      : int   = 0
        self._alerts           : list  = []
        self._force_no_face_mode: bool = False
        self._face_absent_since: float | None = None
        self._audio_lip_mismatch_streak: int = 0
        self._latest_identity  : dict  = {
            "verified": True, "similarity": 1.0,
            "mismatch": False, "liveness": True, "no_face": False,
        }
        self._latest_multi_result: dict = {
            "face_count": 0, "faces": [], "multiple_faces": False,
            "confirmed": False, "duration": 0.0,
        }
        self._last_multi_run_ts : float = 0.0
        self._latest_env_result : dict  = {
            "flag": False, "objects": [], "unauthorized": [], "objects_detected": [],
        }
        self._last_env_run_ts   : float = 0.0
        self._absent_streak     : int   = 0
        self._corner_gaze_window: deque = deque(maxlen=30)

        print("[VERA] Pipeline ready.")

    def update_audio_activity(self, energy: float, has_speech: bool, timestamp: float = None):
        ts = float(timestamp) if timestamp is not None else time.time()
        self._latest_audio_energy = max(0.0, float(energy or 0.0))
        self._latest_audio_has_speech = bool(has_speech)
        self._latest_audio_activity_ts = ts

    def has_recent_audio_activity(self, max_age_seconds: float = 5.0) -> bool:
        if self._latest_audio_activity_ts <= 0.0:
            return False
        if (time.time() - self._latest_audio_activity_ts) > max_age_seconds:
            return False
        return self._latest_audio_has_speech or (self._latest_audio_energy >= self.MIN_SPEECH_ENERGY)

    def _compute_av_sync(self, has_audio: bool, lip_mov: float, mouth_open: bool) -> dict:
        visual_now = clamp01(((float(lip_mov) - 0.02) / 0.18) + (0.25 if mouth_open else 0.0))
        self._visual_activity_window.append(visual_now)
        visual_avg = float(np.mean(self._visual_activity_window)) if self._visual_activity_window else visual_now

        if has_audio:
            score = clamp01(0.18 + (0.82 * visual_avg))
            risk = clamp01((0.55 - score) / 0.55) if score < 0.55 else 0.0
            if score >= 0.72:
                verdict = "Synced — speech activity matches mouth movement"
            elif score >= 0.45:
                verdict = "Partial mismatch — weak visual speech support"
            else:
                verdict = "Mismatch — speech detected without matching lip activity"
        else:
            if visual_avg > 0.45:
                score = 0.55
                risk = 0.10
                verdict = "Mouth active without clear speech segment"
            else:
                score = 1.0
                risk = 0.0
                verdict = "No active speech segment"

        return {
            "score": round(float(score), 3),
            "is_synced": bool(score >= 0.45),
            "risk": round(float(risk), 3),
            "char_similarity": None,
            "word_overlap": None,
            "len_ratio": None,
            "lip_text": "",
            "audio_text": self._latest_audio,
            "visual_activity": round(float(visual_avg), 3),
            "verdict": verdict,
            "data_available": True,
        }

    def _run_behavior(self, frame: np.ndarray) -> dict:
        try:
            return self.behavior.analyze(frame)
        except Exception as e:
            print(f"[VERA] Behavior error: {e}")
            return self.behavior._empty()

    def _run_emotion(self, frame: np.ndarray, behavior_data: dict) -> dict:
        face_crop = frame
        if behavior_data.get("face_detected") and behavior_data.get("landmarks"):
            lm = behavior_data["landmarks"]
            h, w = frame.shape[:2]
            xs = [min(max(l.x * w, 0), w) for l in lm]
            ys = [min(max(l.y * h, 0), h) for l in lm]
            if xs and ys:
                x_min, x_max = int(min(xs)), int(max(xs))
                y_min, y_max = int(min(ys)), int(max(ys))
                pad_x = (x_max - x_min) * 0.16
                pad_y = (y_max - y_min) * 0.16
                x1 = int(max(x_min - pad_x, 0))
                y1 = int(max(y_min - pad_y, 0))
                x2 = int(min(x_max + pad_x, w))
                y2 = int(min(y_max + pad_y, h))
                if x2 > x1 and y2 > y1:
                    face_crop = frame[y1:y2, x1:x2].copy()
        try:
            return self.emotion.analyze(face_crop)
        except Exception as e:
            print(f"[VERA] Emotion error: {e}")
            return self.emotion._empty("Emotion module error")

    def _run_lip_ext(self, frame: np.ndarray) -> tuple:
        if self._frame_count % 5 == 0:
            lip_mov           = self.lip_ext.get_lip_movement_score(frame)
            lip_gray, lip_pts = self.lip_ext.extract(frame)
            mouth_open, _     = self.lip_ext.is_mouth_open(frame)
            return (lip_mov, lip_gray, lip_pts, mouth_open)
        else:
            return getattr(self, '_cached_lip', (0.0, None, None, False))

    def _signal_entry(self, value: float, confidence: float = 1.0,
                      available: bool = True, reason: str = "") -> dict:
        return {
            "value":      clamp01(value),
            "confidence": clamp01(confidence),
            "available":  bool(available),
            "reason":     reason,
        }

    def _build_deception_data(self, scorer_result: dict) -> dict:
        severity = scorer_result["severity"]
        verdicts = {
            "CLEAN":  "No significant indicators",
            "LOW":    "Minor behavioral indicators",
            "MEDIUM": "Moderate behavioral indicators",
            "HIGH":   "Significant behavioral indicators",
        }
        return {
            "score":            scorer_result["risk_score"],
            "verdict":          verdicts.get(severity, severity),
            "level":            severity.lower(),
            "flags":            scorer_result["active_flags"],
            "running_average":  scorer_result["risk_score"],
            "all_signals":      [
                name for name, data in scorer_result["breakdown"].items()
                if data.get("contribution", 0.0) > 0
            ],
            "top_contributors": scorer_result.get("top_contributors", []),
            "cooc_active":      len(scorer_result["active_flags"]),
            "cooc_bonus":       0.0,
        }

    # ── Frame processing ──────────────────────────────────────────────────────
    def process_frame(self, frame: np.ndarray, has_audio: bool = False,
                      security_flags: dict = None) -> dict:
        if security_flags is None:
            security_flags = {}
        self._frame_count += 1
        frame_t0 = time.perf_counter()
        t0 = time.time()

        frame = self.calibrator.preprocess_frame(frame)
        _fl.set_frame_seq(self._frame_count)

        _t = time.perf_counter()
        behavior_data = self._run_behavior(frame)
        behavior_ms   = round((time.perf_counter() - _t) * 1000.0, 2)

        # ── No-face gate ──────────────────────────────────────────────────────
        if not behavior_data.get("face_detected", False) or not behavior_data.get("landmarks"):
            self._absent_streak += 1
            now = time.time()
            if self._face_absent_since is None:
                self._face_absent_since = now
            absent_seconds = max(0.0, now - self._face_absent_since)
            hard_no_face = absent_seconds >= self.NO_FACE_HARD_DELAY_SECONDS
            self._force_no_face_mode = hard_no_face

            if has_audio:
                sync = {
                    "score": 0.10,
                    "is_synced": False,
                    "risk": 0.90,
                    "char_similarity": None,
                    "word_overlap": None,
                    "len_ratio": None,
                    "lip_text": "",
                    "audio_text": self._latest_audio,
                    "visual_activity": 0.0,
                    "verdict": "Mismatch — speech activity detected but no visible face",
                    "data_available": True,
                }
            else:
                sync = {
                    "score": 1.0,
                    "is_synced": True,
                    "risk": 0.0,
                    "char_similarity": None,
                    "word_overlap": None,
                    "len_ratio": None,
                    "lip_text": "",
                    "audio_text": self._latest_audio,
                    "visual_activity": 0.0,
                    "verdict": "No active speech segment",
                    "data_available": True,
                }
            self._latest_sync = sync

            if hard_no_face:
                deception_data = {
                    "score": self.NO_FACE_HARD_SCORE,
                    "verdict": "Face not visible — maximum risk",
                    "level": "high",
                    "flags": ["no_face_detected"],
                    "running_average": self.NO_FACE_HARD_SCORE,
                    "all_signals": ["no_face_detected"],
                    "top_contributors": [{"signal": "no_face_detected", "contribution": 1.0}],
                    "cooc_active": 1,
                    "cooc_bonus": 0.0,
                }
            else:
                current = self.deception.get_current()
                deception_data = {
                    "score": round(float(current.get("risk_score", 0.0)), 1),
                    "verdict": f"Face absent ({absent_seconds:.1f}s) — hard max at {self.NO_FACE_HARD_DELAY_SECONDS:.1f}s",
                    "level": str(current.get("severity", "LOW")).lower(),
                    "flags": list(current.get("active_flags", [])),
                    "running_average": round(float(current.get("running_average", current.get("risk_score", 0.0))), 1),
                    "all_signals": list(current.get("active_flags", [])),
                    "top_contributors": list(current.get("top_contributors", [])),
                    "cooc_active": len(current.get("active_flags", [])),
                    "cooc_bonus": 0.0,
                }

            processing_ms = round((time.time() - t0) * 1000, 1)
            total_ms = round((time.perf_counter() - frame_t0) * 1000.0, 2)
            perf_data = {
                "total_ms": total_ms, "behavior_ms": behavior_ms,
                "emotion_ms": 0.0, "multi_face_ms": 0.0,
                "environment_ms": 0.0, "scorer_ms": 0.0,
                "multi_face_ran": False, "environment_ran": False,
                "multi_face_cache_age_ms": None,
                "environment_cache_age_ms": None,
                "no_face_mode": True,
                "forced_no_face_max": hard_no_face,
            }
            return {
                "frame_id":        self._frame_count,
                "processing_ms":   processing_ms,
                "annotated_frame": frame,
                "face_detected":   False,
                "emotion":         self.emotion._empty("No face detected"),
                "behavior":        behavior_data,
                "deception":       deception_data,
                "sync":            sync,
                "lip_text":        "",
                "lip_movement":    0.0,
                "mouth_open":      False,
                "perf":            perf_data,
                "alerts":          list(self._alerts[-5:]),
                "exam_flags": {
                    "face_absent":           True,
                    "identity_mismatch":     False,
                    "multi_face":            False,
                    "corner_gaze_sustained": False,
                    "phone_suspected":       False,
                    "absent_streak":         self._absent_streak,
                    "absent_seconds":        round(absent_seconds, 2),
                    "corner_ratio":          0.0,
                    "env_objects":           [],
                    "env_unauthorized":      [],
                },
            }

        # ── Face present — FIX: reset streak to 0 IMMEDIATELY ────────────────
        # Old code had a secondary check that could leave streak at 1-2 even
        # after face returned, causing lingering no_face signal.
        if self._force_no_face_mode:
            # Ensure immediate recovery from hard no-face mode without stale risk carryover.
            self.deception.reset()
            self._force_no_face_mode = False
        self._face_absent_since = None
        self._absent_streak = 0

        lip_mov, lip_gray, lip_pts, mouth_open = self._run_lip_ext(frame)

        _te = time.perf_counter()
        emotion_data = self._run_emotion(frame, behavior_data)
        emotion_ms   = round((time.perf_counter() - _te) * 1000.0, 2)

        if self._frame_count % 5 == 0:
            self._cached_lip = (lip_mov, lip_gray, lip_pts, mouth_open)

        face_absent = False  # streak just reset to 0

        # FIX: run env detector every 2 frames (was 4) for faster phone detection
        multi_face_ms = env_ms = 0.0
        multi_face_ran = env_ran = False

        if self._frame_count % 3 == 0:
            try:
                _tm = time.perf_counter()
                self._latest_multi_result = self.multi_face.detect(frame)
                multi_face_ms = round((time.perf_counter() - _tm) * 1000.0, 2)
                multi_face_ran = True
                self._last_multi_run_ts = time.time()
            except Exception as exc:
                print(f"[VERA] Multi-face error: {exc}")

        # FIX: every 2 frames instead of 4
        if self._frame_count % 2 == 0:
            try:
                _tenv = time.perf_counter()
                self._latest_env_result = self.environment.check(frame)
                env_ms = round((time.perf_counter() - _tenv) * 1000.0, 2)
                env_ran = True
                self._last_env_run_ts = time.time()
            except Exception as exc:
                print(f"[VERA] Environment error: {exc}")

        multi_result    = dict(self._latest_multi_result)
        env_result      = dict(self._latest_env_result)
        multi_face      = multi_result['confirmed']
        phone_suspected = multi_face or env_result.get('flag', False)

        gdir = behavior_data.get("gaze", {}).get("direction", "center")
        self._corner_gaze_window.append(gdir in ("upper_right", "upper_left", "right", "left"))
        corner_ratio          = sum(self._corner_gaze_window) / max(len(self._corner_gaze_window), 1)
        corner_gaze_sustained = corner_ratio > 0.45

        if has_audio:
            if lip_mov < 0.03 and not mouth_open:
                self._audio_lip_mismatch_streak += 1
            else:
                self._audio_lip_mismatch_streak = max(0, self._audio_lip_mismatch_streak - 1)
        else:
            self._audio_lip_mismatch_streak = max(0, self._audio_lip_mismatch_streak - 1)

        sync = self._compute_av_sync(has_audio, lip_mov, mouth_open)
        if has_audio and self._audio_lip_mismatch_streak >= 4:
            sync["score"] = min(float(sync.get("score", 1.0)), 0.18)
            sync["risk"] = max(float(sync.get("risk", 0.0)), 0.82)
            sync["is_synced"] = False
            sync["verdict"] = "Mismatch — sustained speech with minimal lip activity"
        self._latest_sync = sync

        if self._frame_count % 8 == 0:
            try:
                self._latest_identity = self.identity.verify(frame)
            except Exception as exc:
                print(f"[VERA] Identity verify error: {exc}")

        adaptive        = self.calibrator.get_adaptive_thresholds()
        gaze_threshold  = float(adaptive.get("gaze_threshold", 0.60))
        emotion_threshold = float(adaptive.get("emotion_threshold", 0.50))

        gaze_avoid  = max(
            float(behavior_data.get("gaze_avoidance_rate", 0.0)),
            float(corner_ratio),
        )
        gaze_value  = clamp01((gaze_avoid - gaze_threshold) / max(1e-3, 1.0 - gaze_threshold))

        yaw       = abs(float(behavior_data.get("head_pose", {}).get("yaw",   0.0)))
        pitch     = abs(float(behavior_data.get("head_pose", {}).get("pitch", 0.0)))
        head_mag  = max(yaw, pitch)
        head_value = clamp01((head_mag - 12.0) / 35.0)

        multi_faces    = multi_result.get("faces", [])
        top_multi_conf = max((float(f.get("conf", 0.0)) for f in multi_faces), default=0.0)
        multi_raw = 0.0
        if multi_result.get("face_count", 0) > 1:
            multi_raw = 0.55 * top_multi_conf + (0.45 if multi_face else 0.15)
        multi_value = clamp01(multi_raw)

        unauth_names = {"cell phone", "laptop", "book"}
        unauth_dets  = [d for d in env_result.get("objects_detected", [])
                        if d.get("class") in unauth_names]
        top_obj_conf = max((float(d.get("confidence", 0.0)) for d in unauth_dets), default=0.0)
        obj_value    = clamp01(0.75 * top_obj_conf + (0.20 if env_result.get("flag", False) else 0.0))

        # FIX: no_face_value must be 0.0 when face is present (streak just reset)
        no_face_value = 0.0

        emo_label = (emotion_data.get("label") or "").lower()
        emo_conf  = clamp01(float(emotion_data.get("confidence", 0.0)) / 100.0)
        emo_risk  = clamp01(float(emotion_data.get("risk_score", 0.0)))
        emo_raw   = max(emo_conf, emo_risk) if emo_label in ("fear", "surprise", "contempt", "disgust", "angry") else 0.0
        emotion_value = clamp01((emo_raw - emotion_threshold) / max(1e-3, 1.0 - emotion_threshold))

        if has_audio:
            sync_score = sync.get("score") or 1.0
            mismatch_raw = max(float(sync.get("risk", 0.0)), 1.0 - float(sync_score))
            if self._audio_lip_mismatch_streak >= 4:
                mismatch_raw = max(mismatch_raw, 0.95)
            elif not sync.get("is_synced", True) and lip_mov > 0.05:
                mismatch_raw = max(mismatch_raw, 0.20)
            audio_value = clamp01(mismatch_raw)
        else:
            audio_value = 0.0

        tab_events    = sum(bool(security_flags.get(k)) for k in ("tab_changed", "window_blur", "copy_paste"))
        tab_value     = clamp01(0.60 + 0.20 * tab_events) if tab_events else 0.0
        screen_events = sum(bool(security_flags.get(k)) for k in ("fullscreen_exit", "screen_stopped"))
        screen_value  = clamp01(0.75 + 0.20 * screen_events) if screen_events else 0.0

        identity_available = self.identity.is_enrolled()
        similarity         = float(self._latest_identity.get("similarity", 1.0))
        mismatch           = bool(self._latest_identity.get("mismatch", False)) if identity_available else False
        liveness_ok        = bool(self._latest_identity.get("liveness", True))
        identity_value     = 0.0
        if mismatch:
            identity_value = clamp01(((0.45 - similarity) / 0.45) + 0.35)
        if identity_available and not liveness_ok:
            identity_value = max(identity_value, 0.75)

        speaker_flag      = security_flags.get("second_speaker")
        speaker_score     = security_flags.get("second_speaker_score")
        speaker_available = speaker_flag is not None or speaker_score is not None
        second_speaker_value = 0.0
        if speaker_score is not None:
            second_speaker_value = clamp01(float(speaker_score))
        if speaker_flag is True:
            second_speaker_value = max(second_speaker_value, 0.80)

        gaze_risk = float(behavior_data.get("gaze_interpretation", {}).get("risk", 0.0))
        self.calibrator.feed_sample(gaze_risk, emotion_value)

        signals = {
            "gaze_away":           self._signal_entry(gaze_value, 0.78, True, "gaze_avoidance"),
            "head_turned":         self._signal_entry(head_value, 0.80, True, "head_pose"),
            "multiple_faces":      self._signal_entry(multi_value, max(0.50, top_multi_conf), True, "retinaface"),
            "unauthorized_object": self._signal_entry(obj_value, max(0.45, top_obj_conf),
                                                      bool(getattr(self.environment, "_has_onnx", False)),
                                                      "yolov8"),
            "emotion_distress":    self._signal_entry(emotion_value, max(0.50, emo_conf),
                                                      emotion_data.get("backend") != "none",
                                                      "deepface_emotion"),
            "audio_mismatch":      self._signal_entry(audio_value, 0.88 if has_audio else 0.0,
                                                      bool(has_audio), "audio_lip_sync"),
            "second_speaker":      self._signal_entry(second_speaker_value, 0.85 if speaker_available else 0.0,
                                                      bool(speaker_available), "speaker_verification"),
            "tab_switch":          self._signal_entry(tab_value, 0.95, True, "browser_security"),
            "screen_share_lost":   self._signal_entry(screen_value, 0.98, True, "screen_security"),
            "no_face_detected":    self._signal_entry(no_face_value, 1.0, True, "face_present"),
            "identity_mismatch":   self._signal_entry(identity_value,
                                                      1.0 if identity_available else 0.0,
                                                      bool(identity_available), "insightface"),
        }

        _ts = time.perf_counter()
        scorer_result  = self.deception.update(signals)
        scorer_ms      = round((time.perf_counter() - _ts) * 1000.0, 2)
        deception_data = self._build_deception_data(scorer_result)

        annotated = frame
        self._check_alerts(deception_data, behavior_data, emotion_data)

        ts = time.strftime("%H:%M:%S")
        def _recent(sub): return any(sub in a["msg"] for a in self._alerts[-4:])

        if multi_face and not _recent("Multiple face"):
            self._alerts.append({"time": ts, "msg": "⚠ Multiple faces detected"})
        if face_absent and not _recent("absent"):
            self._alerts.append({"time": ts, "msg": "⚠ Face absent — candidate left frame"})
        if phone_suspected and not _recent("Phone/Device"):
            self._alerts.append({"time": ts, "msg": "📱 Phone/Device suspected in frame"})

        if security_flags.get("tab_changed") and not _recent("External Tab"):
            self._alerts.append({"time": ts, "msg": "🚫 Critical: External Tab usage detected!"})
        if security_flags.get("window_blur") and not _recent("Window Focus"):
            self._alerts.append({"time": ts, "msg": "🚫 Critical: Window focus lost during session!"})
        if security_flags.get("copy_paste") and not _recent("Copy/Paste"):
            self._alerts.append({"time": ts, "msg": "🚫 Critical: Copy/Paste attempt blocked!"})
        if security_flags.get("fullscreen_exit") and not _recent("Fullscreen"):
            self._alerts.append({"time": ts, "msg": "🚫 Critical: Fullscreen mode exited!"})
        if security_flags.get("screen_stopped") and not _recent("Screen Sharing"):
            self._alerts.append({"time": ts, "msg": "🚫 Critical: Screen Sharing was revoked!"})

        illum_var    = behavior_data.get("illumination_var", 0.0)
        saccade_rate = behavior_data.get("rapid_saccade_rate", 0.0)
        if illum_var > 400.0 and not _recent("Illumination"):
            self._alerts.append({"time": ts, "msg": "💡 Illumination Anomaly: Screen flash detected"})
        if saccade_rate > 0.35 and not _recent("Frequent Off-Screen"):
            self._alerts.append({"time": ts, "msg": "👀 Rapid Lap-Glancing: Frequent Off-Screen Glancing"})

        ms     = round((time.time() - t0) * 1000, 1)
        now_ts = time.time()
        perf_data = {
            "total_ms":    round((time.perf_counter() - frame_t0) * 1000.0, 2),
            "behavior_ms": behavior_ms,
            "emotion_ms":  emotion_ms,
            "multi_face_ms": multi_face_ms,
            "environment_ms": env_ms,
            "scorer_ms":   scorer_ms,
            "multi_face_ran":  multi_face_ran,
            "environment_ran": env_ran,
            "multi_face_cache_age_ms":   round(max(0.0, (now_ts - self._last_multi_run_ts)   * 1000.0), 1) if self._last_multi_run_ts else None,
            "environment_cache_age_ms":  round(max(0.0, (now_ts - self._last_env_run_ts)    * 1000.0), 1) if self._last_env_run_ts   else None,
            "no_face_mode":       False,
            "forced_no_face_max": False,
        }

        return {
            "frame_id":            self._frame_count,
            "processing_ms":       ms,
            "emotion":             emotion_data,
            "behavior":            behavior_data,
            "lip_text":            "",
            "lipnet_display_only": False,
            "audio_text":          self._latest_audio,
            "sync":                sync,
            "deception":           deception_data,
            "perf":                perf_data,
            "lip_movement":        lip_mov,
            "mouth_open":          mouth_open,
            "annotated_frame":     annotated,
            "alerts":              list(self._alerts[-5:]),
            "exam_flags": {
                "face_absent":           False,
                "identity_mismatch":     bool(identity_available and mismatch),
                "multi_face":            multi_face,
                "corner_gaze_sustained": corner_gaze_sustained,
                "phone_suspected":       phone_suspected,
                "absent_streak":         self._absent_streak,
                "corner_ratio":          round(corner_ratio, 3),
                "env_objects":           env_result.get("objects", []),
                "env_unauthorized":      env_result.get("unauthorized", []),
            },
        }

    def set_audio_text(self, audio_text: str):
        """
        Update latest transcript text. AV sync scoring is visual-audio activity
        based and happens per-frame in process_frame().
        """
        if not audio_text:
            return
        # Filter hallucinations
        stripped = audio_text.strip().lower().rstrip(".")
        if stripped in WHISPER_HALLUCINATIONS:
            return
        # Ignore very short transcripts (likely misfires)
        if len(audio_text.strip()) < 4:
            return
        self._latest_audio    = audio_text
        self._latest_audio_ts = time.time()

    def get_session_summary(self) -> dict:
        current = self.deception.get_current()
        signals_seen = set()
        try:
            for entry in list(getattr(self.deception, '_history', [])):
                for flag in entry.get('flags', []):
                    signals_seen.add(flag)
        except Exception:
            pass
        return {
            'final_score':           round(float(current.get('risk_score', 0.0)), 1),
            'severity':              current.get('severity', 'CLEAN'),
            'active_flags':          list(current.get('active_flags', [])),
            'all_signals_seen':      list(signals_seen),
            'running_average':       round(float(current.get('running_average', 0.0)), 1),
            'alerts':                list(self._alerts),
            'last_sync':             self._latest_sync,
            'audio_transcription':   self._latest_audio,
            'last_lip_text':         "",
            'total_frames_analyzed': self._frame_count,
        }

    # ── Overlay helpers ───────────────────────────────────────────────────────
    def _draw_emotion_overlay(self, frame: np.ndarray, emo: dict) -> np.ndarray:
        h = frame.shape[0]
        label = f"{emo.get('label','?')} {emo.get('confidence',0):.0f}%"
        color = emo.get("color", (255, 255, 255))
        cv2.putText(frame, label, (10, h - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.60, color, 2)
        return frame

    def _draw_risk_bar(self, frame: np.ndarray, score: float) -> np.ndarray:
        h, w = frame.shape[:2]
        bw, bh = 200, 14
        x, y = w - bw - 12, 10
        cv2.rectangle(frame, (x, y), (x + bw, y + bh), (40, 40, 40), -1)
        fill = int(bw * score / 100)
        c = (0, 200, 0) if score < 35 else (0, 140, 255) if score < 65 else (0, 0, 220)
        cv2.rectangle(frame, (x, y), (x + fill, y + bh), c, -1)
        cv2.putText(frame, f"Risk: {score:.0f}%", (x, y + bh + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.50, c, 1)
        return frame

    # ── Alert system ──────────────────────────────────────────────────────────
    def _check_alerts(self, deception, behavior, emotion):
        ts = time.strftime("%H:%M:%S")
        def _recent(msg_substr):
            return any(msg_substr in a["msg"] for a in self._alerts[-4:])
        if deception["score"] >= 65 and not _recent("High risk"):
            self._alerts.append({"time": ts, "msg": f"High risk score: {deception['score']:.0f}%"})
        if not behavior.get("face_detected", True) and not _recent("Face not"):
            self._alerts.append({"time": ts, "msg": "[!] HIGH RISK — Face not visible (evasion)"})
        if behavior.get("blink", {}).get("elevated") and not _recent("blink"):
            r = behavior["blink"]["rate"]
            self._alerts.append({"time": ts, "msg": f"Elevated blink rate: {r:.0f}/min"})
        if behavior.get("head_pose", {}).get("is_turned") and not _recent("Head"):
            d = behavior["head_pose"]["direction"]
            self._alerts.append({"time": ts, "msg": f"Head turned: {d}"})
        if emotion.get("is_deceptive_emotion") and not _recent(emotion.get("label", "")):
            self._alerts.append({"time": ts, "msg": f"Deceptive emotion: {emotion['label']}"})

    # ── Full video analysis ───────────────────────────────────────────────────
    def analyze_video_file(self, video_path: str, output_path: str = None) -> dict:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            return {"error": f"Cannot open: {video_path}"}

        fps    = int(cap.get(cv2.CAP_PROP_FPS)) or 25
        vw     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        vh     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        writer = None
        if output_path:
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            writer = cv2.VideoWriter(output_path, fourcc, fps, (vw, vh))

        audio_text = ""
        speech_segments = []
        try:
            ar = self.audio.transcribe_file(video_path)
            audio_text = ar.get("text", "")
            for seg in ar.get("segments", []) or []:
                try:
                    start = float(seg.get("start", 0.0))
                    end = float(seg.get("end", start))
                except (TypeError, ValueError):
                    continue
                if end > start:
                    speech_segments.append((start, end))
            if audio_text:
                self.set_audio_text(audio_text)
        except Exception:
            pass

        frame_results  = []
        idx            = 0
        emotion_counts = {}
        last_signals   = []
        last_gaze      = "unknown"
        last_blink_rate = 0.0
        last_head      = "Unknown"
        sync_scores = []

        while True:
            ret, frame = cap.read()
            if not ret:
                break
            idx += 1
            if idx % 3 != 0:
                continue
            frame_ts = idx / float(max(fps, 1))
            has_audio_frame = any(start <= frame_ts <= end for start, end in speech_segments)
            if not speech_segments:
                has_audio_frame = bool(audio_text)
            r = self.process_frame(frame, has_audio=has_audio_frame)

            emo_dom = r["emotion"].get("dominant", "neutral")
            emotion_counts[emo_dom] = emotion_counts.get(emo_dom, 0) + 1
            last_signals    = r["deception"].get("all_signals", [])
            last_gaze       = r["behavior"]["gaze"]["direction"]
            last_blink_rate = r["behavior"]["blink"]["rate"]
            last_head       = r["behavior"]["head_pose"]["direction"]
            if r.get("sync", {}).get("score") is not None:
                try:
                    sync_scores.append(float(r["sync"]["score"]))
                except (TypeError, ValueError):
                    pass

            frame_results.append({
                "frame_id":  r["frame_id"],
                "emotion":   emo_dom,
                "deception": r["deception"]["score"],
                "gaze":      last_gaze,
                "blink":     last_blink_rate,
                "head":      last_head,
                "lip_text":  "",
            })
            if writer:
                writer.write(r["annotated_frame"])

        cap.release()
        if writer:
            writer.release()

        summary = self.get_session_summary()
        summary.update({
            "audio_transcription":  audio_text,
            "total_frames":         idx,
            "analyzed_frames":      len(frame_results),
            "alerts":               self._alerts,
            "video_path":           video_path,
            "emotion_distribution": emotion_counts,
            "last_signals":         last_signals,
            "last_gaze":            last_gaze,
            "last_blink_rate":      round(last_blink_rate, 1),
            "last_head":            last_head,
            "last_lip_text":        "",
            "av_sync_score_avg":    round(float(np.mean(sync_scores)), 3) if sync_scores else None,
            "speech_segments":      len(speech_segments),
        })
        return {"summary": summary, "frames": frame_results}

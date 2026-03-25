"""
VERA - Emotion Detector  (Production - v4)
Primary: DeepFace with opencv backend (fastest + accurate)
Background thread: DeepFace runs asynchronously, never blocking the pipeline
Temporal smoothing: majority vote over 12 frames for stability
Fix: First frame runs synchronously to avoid null/stale initial results
"""

import cv2
import numpy as np
import threading
import time
from collections import deque, Counter

EMOTION_META = {
    "angry":    {"risk": 0.45, "label": "Angry",    "color": (0, 0, 220),    "icon": "😠"},
    "contempt": {"risk": 0.65, "label": "Contempt", "color": (60, 0, 160),   "icon": "😒"},
    "disgust":  {"risk": 0.50, "label": "Disgust",  "color": (80, 0, 180),   "icon": "🤢"},
    "fear":     {"risk": 0.70, "label": "Fear",     "color": (0, 100, 255),  "icon": "😨"},
    "happy":    {"risk": 0.05, "label": "Happy",    "color": (0, 200, 0),    "icon": "😊"},
    "sad":      {"risk": 0.30, "label": "Sad",      "color": (180, 100, 0),  "icon": "😢"},
    "surprise": {"risk": 0.35, "label": "Surprise", "color": (200, 200, 0),  "icon": "😮"},
    "neutral":  {"risk": 0.10, "label": "Neutral",  "color": (160, 160, 160),"icon": "😐"},
}
DECEPTION_EMOTIONS = {"contempt", "fear", "disgust", "surprise", "angry"}
SMOOTH_N = 12


class EmotionDetector:
    def __init__(self):
        self._deepface = None
        self._backend = "none"
        self._df_backend = "opencv"
        self._history = deque(maxlen=SMOOTH_N)
        self._score_history = {k: deque(maxlen=SMOOTH_N) for k in EMOTION_META}
        self._last_result = None
        self._first_run_done = False

        # ── Background thread state ──────────────────────────────────────
        self._bg_frame = None
        self._bg_lock = threading.Lock()
        self._bg_event = threading.Event()
        self._bg_running = True
        self._bg_raw = None

        self._load_backends()

        # Start background thread for DeepFace (never blocks the pipeline)
        self._bg_thread = threading.Thread(target=self._bg_worker, daemon=True)
        self._bg_thread.start()

    def _load_backends(self):
        try:
            import deepface
            from deepface import DeepFace
            self._deepface = DeepFace
            self._backend = "deepface"
            try:
                test = np.zeros((48, 48, 3), dtype=np.uint8)
                DeepFace.analyze(test, actions=["emotion"], enforce_detection=False,
                                 detector_backend="ssd", silent=True)
                self._df_backend = "ssd"
                print("[EmotionDetector] DeepFace ready (ssd backend).")
            except Exception:
                self._df_backend = "opencv"
                print("[EmotionDetector] DeepFace ready (opencv backend).")
        except ImportError:
            self._backend = "none"
            import logging
            logging.getLogger(__name__).warning(
                "DeepFace not installed. Emotion detection disabled. "
                "Run: pip install deepface>=0.0.92"
            )

    # ── Background worker thread ────────────────────────────────────────
    def _bg_worker(self):
        """Runs in a separate thread. Picks up frames and processes them
        at its own pace (~1-2 fps). Never blocks the main pipeline."""
        while self._bg_running:
            self._bg_event.wait(timeout=2.0)
            self._bg_event.clear()

            with self._bg_lock:
                frame = self._bg_frame
                self._bg_frame = None

            if frame is None:
                continue

            raw = self._run_analysis(frame)
            if raw is not None:
                with self._bg_lock:
                    self._bg_raw = raw

    def _run_analysis(self, frame):
        """Execute the actual DeepFace analysis (heavy, ~200-400ms)."""
        raw = None
        if self._deepface is not None:
            try:
                r = self._deepface.analyze(
                    frame, actions=["emotion"],
                    enforce_detection=False,
                    detector_backend="skip",
                    silent=True
                )
                r = r[0] if isinstance(r, list) else r
                dom = r["dominant_emotion"]
                sc  = r["emotion"]
                tot = sum(sc.values()) or 1
                sc  = {k: v/tot*100 for k, v in sc.items()}
                if sc.get(dom, 0) < 30.0:
                    dom = "neutral"
                raw = {"dominant": dom, "scores": sc}
            except Exception:
                pass

        return raw

    # ── Main thread API (always returns instantly) ──────────────────────
    def analyze(self, frame: np.ndarray) -> dict:
        """Called by the pipeline. Submits frame to bg thread and returns
        the latest cached result instantly (never blocks).
        Exception: first call runs synchronously to avoid null results."""

        # First call: run synchronously to populate initial result
        if not self._first_run_done and self._last_result is None:
            self._first_run_done = True
            raw = self._run_analysis(frame)
            if raw is not None:
                with self._bg_lock:
                    self._bg_raw = raw
            else:
                # DeepFace couldn't detect anything — return neutral
                return self._empty("Initializing...")

        # Submit frame to background thread (non-blocking)
        with self._bg_lock:
            self._bg_frame = frame.copy()
        self._bg_event.set()

        # Check if background thread has produced a new result
        with self._bg_lock:
            raw = self._bg_raw

        if raw is None:
            if self._last_result is not None:
                return self._last_result
            return self._empty("Analyzing...")

        # Temporal smoothing
        self._history.append(raw["dominant"])
        for emo in EMOTION_META:
            self._score_history[emo].append(raw["scores"].get(emo, 0.0))

        smoothed = Counter(self._history).most_common(1)[0][0]
        avg_scores = {e: float(np.mean(list(h))) for e, h in self._score_history.items() if h}

        meta = EMOTION_META.get(smoothed, EMOTION_META["neutral"])
        micro_expression = (raw["dominant"] != smoothed)
        result = {
            "dominant": smoothed,
            "label": meta["label"],
            "icon": meta["icon"],
            "scores": {k: round(v, 1) for k, v in avg_scores.items()},
            "risk_score": meta["risk"],
            "color": meta["color"],
            "is_deceptive_emotion": smoothed in DECEPTION_EMOTIONS,
            "confidence": round(avg_scores.get(smoothed, 0), 1),
            "raw_dominant": raw["dominant"],
            "micro_expression": micro_expression,
            "backend": self._backend,
            "error": None
        }
        self._last_result = result
        return result


    def _empty(self, reason=""):
        return {
            "dominant": "neutral", "label": "Neutral", "icon": "😐",
            "scores": {k: 0.0 for k in EMOTION_META}, "risk_score": 0.0,
            "color": (160, 160, 160), "is_deceptive_emotion": False,
            "confidence": 0.0, "raw_dominant": "neutral",
            "micro_expression": False,
            "backend": self._backend, "error": reason
        }

    def shutdown(self):
        """Clean shutdown of the background thread."""
        self._bg_running = False
        self._bg_event.set()

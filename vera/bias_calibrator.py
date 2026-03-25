"""
VERA — Bias Calibrator (CLAHE + Adaptive Baseline)
1. CLAHE preprocessing: normalizes frame brightness for equitable
   face detection across skin tones and lighting conditions.
2. Adaptive baseline: collects 30s of personal behavioral data,
   then sets per-candidate thresholds (not universal fixed values).
"""
import cv2
import numpy as np
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

BASELINE_DURATION_SECONDS = 30
CLAHE_CLIP_LIMIT = 2.0
CLAHE_TILE_SIZE = (8, 8)


class BIASCalibrator:
    """
    Two functions:
    1. CLAHE preprocessing — normalizes frame brightness before CV processing.
       Equitable across skin tones and lighting conditions.
    2. Adaptive baseline — collects each candidate's personal behavioral
       baseline for the first 30 seconds. All subsequent thresholds are
       relative to this baseline, not fixed universal values.
    """

    def __init__(self):
        self._clahe = cv2.createCLAHE(
            clipLimit=CLAHE_CLIP_LIMIT,
            tileGridSize=CLAHE_TILE_SIZE
        )
        # Baseline collection
        self._collecting = False
        self._baseline_start = None
        self._gaze_samples = deque(maxlen=300)   # 30s x 10fps
        self._emotion_samples = deque(maxlen=300)
        self._baseline = None

    def preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Apply CLAHE to the luminance channel for lighting normalization.
        Input/output: BGR numpy array.
        """
        lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l_eq = self._clahe.apply(l)
        lab_eq = cv2.merge([l_eq, a, b])
        return cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)

    def start_baseline_collection(self):
        """Call at session start. Collects 30s of normal behavior."""
        self._collecting = True
        self._baseline_start = time.monotonic()
        self._gaze_samples.clear()
        self._emotion_samples.clear()
        self._baseline = None
        logger.info("BiasCalibrator: Baseline collection started.")

    def feed_sample(self, gaze_score: float, emotion_distress: float):
        """Feed each pipeline tick's scores during baseline collection."""
        if not self._collecting:
            return

        self._gaze_samples.append(gaze_score)
        self._emotion_samples.append(emotion_distress)

        elapsed = time.monotonic() - self._baseline_start
        if elapsed >= BASELINE_DURATION_SECONDS:
            self._finalize_baseline()

    def _finalize_baseline(self):
        gaze_arr = np.array(self._gaze_samples)
        emotion_arr = np.array(self._emotion_samples)

        self._baseline = {
            'gaze_mean': float(np.mean(gaze_arr)),
            'gaze_std': float(np.std(gaze_arr)),
            'emotion_mean': float(np.mean(emotion_arr)),
            'emotion_std': float(np.std(emotion_arr)),
            # Adaptive threshold = personal mean + 2 standard deviations
            'gaze_threshold': float(np.mean(gaze_arr) + 2 * np.std(gaze_arr)),
            'emotion_threshold': float(np.mean(emotion_arr) + 2 * np.std(emotion_arr)),
        }
        self._collecting = False
        logger.info(f"BiasCalibrator: Baseline finalized: {self._baseline}")

    def is_baseline_ready(self) -> bool:
        return self._baseline is not None

    def get_adaptive_thresholds(self) -> dict:
        """
        Returns thresholds calibrated to this specific candidate.
        Use these instead of fixed universal thresholds in the pipeline.
        """
        if self._baseline is None:
            # Fall back to conservative defaults if baseline not yet collected
            return {'gaze_threshold': 0.6, 'emotion_threshold': 0.5}
        return {
            'gaze_threshold': self._baseline['gaze_threshold'],
            'emotion_threshold': self._baseline['emotion_threshold']
        }

    def reset(self):
        self._collecting = False
        self._baseline_start = None
        self._gaze_samples.clear()
        self._emotion_samples.clear()
        self._baseline = None

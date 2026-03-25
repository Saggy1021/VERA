"""
VERA - Lip Region Extractor
Uses MediaPipe 0.10+ FaceLandmarker Tasks API to extract lip region.
No model training needed. Feeds directly into existing LipNet model.
"""

import cv2
import numpy as np
import os, sys

# Shared MediaPipe 0.10+ Tasks API wrapper (replaces removed mp.solutions)
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
import face_landmark as _fl

# Outer lip landmark indices from MediaPipe 468-point face mesh
LIPS_OUTER = [
    61, 146, 91, 181, 84, 17, 314, 405, 321,
    375, 291, 308, 324, 318, 402, 317, 14,
    87, 178, 88, 95
]

# Inner lip landmark indices
LIPS_UPPER = [13, 312, 311, 310, 415, 308, 324, 318, 402, 317, 14, 87, 178, 88, 95, 78, 191, 80, 81, 82]
LIPS_LOWER = [14, 317, 402, 318, 324, 308, 415, 310, 311, 312, 13, 82, 81, 80, 191, 78]


class LipExtractor:
    """
    Extracts lip region from video frames using MediaPipe.
    Output is resized to (46, 140) grayscale to match LipNet input.
    Runs face_mesh.process() ONCE per frame and caches results.
    """

    def __init__(self):
        self.prev_landmarks = None

    def _get_landmarks(self, frame):
        """Return the landmark list for the first face, or None.
        Uses detect_bgr() so the BGR frame id is the cache key — the same
        frame object passed from the pipeline to all modules triggers only
        one MediaPipe inference total, not one per module call.
        """
        result = _fl.detect_bgr(frame)
        if not result.face_landmarks:
            return None
        return result.face_landmarks[0]  # list of NormalizedLandmark .x/.y/.z

    def extract(self, frame):
        """
        Extract lip region from a BGR frame.
        Returns:
            lip_gray  : np.ndarray shape (46, 140) grayscale, or None
            lip_points: np.ndarray of (x, y) coords
        """
        lm = self._get_landmarks(frame)
        if lm is None:
            return None, None

        h, w = frame.shape[:2]
        points = []
        for idx in LIPS_OUTER:
            points.append((int(lm[idx].x * w), int(lm[idx].y * h)))
        points = np.array(points)

        pad = 18
        x_min = max(0, points[:, 0].min() - pad)
        x_max = min(w, points[:, 0].max() + pad)
        y_min = max(0, points[:, 1].min() - pad)
        y_max = min(h, points[:, 1].max() + pad)

        lip_crop = frame[y_min:y_max, x_min:x_max]
        if lip_crop.size == 0:
            return None, None

        # Convert to grayscale and resize to LipNet input (46 H x 140 W)
        lip_gray = cv2.cvtColor(lip_crop, cv2.COLOR_BGR2GRAY)
        lip_gray = cv2.resize(lip_gray, (140, 46))

        # Standardise distribution directly at extraction to match LipNet training constraints
        lip_gray = lip_gray.astype(np.float32) / 255.0

        self.prev_landmarks = lm
        return lip_gray, points

    def is_mouth_open(self, frame):
        """Returns True if mouth is open, with openness distance."""
        lm = self._get_landmarks(frame)
        if lm is None:
            return False, 0
        h = frame.shape[0]
        upper_y = lm[13].y * h
        lower_y = lm[14].y * h
        dist = abs(lower_y - upper_y)
        return dist > 6, round(dist, 2)

    def get_lip_movement_score(self, frame):
        """
        Returns a movement score 0-1 comparing current landmarks
        to previous frame landmarks. Used for silent mouthing detection.
        """
        lm = self._get_landmarks(frame)
        if lm is None or self.prev_landmarks is None:
            return 0.0

        movement = 0.0
        for idx in LIPS_OUTER:
            movement += abs(lm[idx].x - self.prev_landmarks[idx].x)
            movement += abs(lm[idx].y - self.prev_landmarks[idx].y)

        # prev_landmarks is updated in extract(); don't update here
        return round(min(movement / len(LIPS_OUTER) * 1000, 1.0), 4)

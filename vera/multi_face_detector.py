"""
Multi-face detector — uses InsightFace RetinaFace for detection.

Replaces the mediapipe 0.9.x mp.solutions.face_detection implementation.
InsightFace is already a project dependency (buffalo_sc model downloaded).
Public interface is unchanged so vera_pipeline.py needs no edits.
"""
from __future__ import annotations

import time
import logging
import numpy as np

logger = logging.getLogger(__name__)

# Temporal confirmation: multiple faces must persist for this many seconds
_CONFIRM_SECONDS = 3.0


class MultiFaceDetector:
    """
    Detects multiple faces in a frame using InsightFace RetinaFace.

    Returns a dict with face_count, multiple_faces flag, temporal
    confirmation flag (True after _CONFIRM_SECONDS of continuous
    multi-face detection), and bounding boxes.
    """

    def __init__(self) -> None:
        self._app = None
        self._multi_face_since: float | None = None
        self._confirmed = False
        self._load_model()

    def _load_model(self) -> None:
        try:
            import insightface
            from insightface.app import FaceAnalysis
            self._app = FaceAnalysis(
                name="buffalo_sc",
                allowed_modules=["detection"],  # detection only — skip recognition
            )
            self._app.prepare(ctx_id=-1, det_size=(640, 640))
            logger.info("[MultiFaceDetector] InsightFace RetinaFace ready.")
        except Exception as exc:
            logger.warning(
                "[MultiFaceDetector] InsightFace load failed: %s. "
                "Multi-face detection disabled — will return defaults.",
                exc,
            )
            self._app = None

    # ------------------------------------------------------------------ #
    #  Public interface (unchanged from original)                          #
    # ------------------------------------------------------------------ #

    def detect(self, frame: np.ndarray) -> dict:
        """
        Run multi-face detection on a single BGR frame.

        Parameters
        ----------
        frame : np.ndarray
            BGR image array (as returned by OpenCV).

        Returns
        -------
        dict with keys:
            face_count     int   — number of faces detected
            multiple_faces bool  — True if face_count > 1
            confirmed      bool  — True if multiple faces for >= 3 s
            faces          list  — [{"bbox": [x1,y1,x2,y2], "conf": float}]
        """
        if self._app is None or frame is None:
            return self._default_result()

        try:
            # insightface expects BGR; frame is already BGR from OpenCV
            faces = self._app.get(frame)
        except Exception as exc:
            logger.debug("[MultiFaceDetector] detect error: %s", exc)
            return self._default_result()

        face_count = len(faces)
        multiple = face_count > 1

        # Temporal confirmation logic (unchanged from original behaviour)
        now = time.monotonic()
        if multiple:
            if self._multi_face_since is None:
                self._multi_face_since = now
            elapsed = now - self._multi_face_since
            if elapsed >= _CONFIRM_SECONDS:
                self._confirmed = True
        else:
            self._multi_face_since = None
            self._confirmed = False

        face_list = []
        for f in faces:
            box = f.bbox.astype(int).tolist()  # [x1, y1, x2, y2]
            conf = float(f.det_score) if hasattr(f, "det_score") else 1.0
            face_list.append({"bbox": box, "conf": conf})

        return {
            "face_count": face_count,
            "multiple_faces": multiple,
            "confirmed": self._confirmed,
            "faces": face_list,
        }

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _default_result() -> dict:
        return {
            "face_count": 0,
            "multiple_faces": False,
            "confirmed": False,
            "faces": [],
        }

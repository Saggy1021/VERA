"""
Shared MediaPipe 0.10+ FaceLandmarker singleton for VERA.

MediaPipe 0.10 removed mp.solutions; this module wraps the new Tasks API.
The singleton is lazily initialised once and shared across all callers.
Thread-safe frame caching via a sequential frame counter set by the pipeline.
"""
import os
import cv2
import threading
import mediapipe as mp
from mediapipe.tasks import python as _mp_py
from mediapipe.tasks.python import vision as _mp_vis

BASE_DIR   = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_PATH = os.path.join(BASE_DIR, "models", "face_landmarker.task")

_landmarker  = None   # singleton FaceLandmarker (IMAGE mode)
_lock        = threading.Lock()

# Thread-safe frame cache using sequential frame counter
_cache_seq    = -1     # sequential frame number set by pipeline
_cache_result = None   # cached FaceLandmarkerResult


def _get_landmarker():
    global _landmarker
    if _landmarker is not None:
        return _landmarker
    with _lock:
        if _landmarker is not None:
            return _landmarker
        if not os.path.exists(MODEL_PATH):
            raise FileNotFoundError(
                f"MediaPipe model not found: {MODEL_PATH}\n"
                "Run the following once to download it:\n"
                "  python -c \"import urllib.request; urllib.request.urlretrieve("
                "'https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                "face_landmarker/float16/1/face_landmarker.task', 'models/face_landmarker.task')\""
            )
        base_opts = _mp_py.BaseOptions(model_asset_path=MODEL_PATH)
        options   = _mp_vis.FaceLandmarkerOptions(
            base_options=base_opts,
            running_mode=_mp_vis.RunningMode.IMAGE,
            num_faces=2,
            min_face_detection_confidence=0.35,
            min_face_presence_confidence=0.35,
            min_tracking_confidence=0.35,
            output_face_blendshapes=False,
            output_facial_transformation_matrixes=False,
        )
        _landmarker = _mp_vis.FaceLandmarker.create_from_options(options)
        print("[VERA] MediaPipe FaceLandmarker created (conf=0.35)")
        return _landmarker


def set_frame_seq(seq: int):
    """Called by VERAPipeline before submitting parallel tasks.
    All modules checking detect_bgr() for this frame will get the cached result."""
    global _cache_seq
    _cache_seq = seq


def detect(rgb_frame, frame_seq: int = -1) -> "_mp_vis.FaceLandmarkerResult":
    """Run face landmark detection on an RGB frame."""
    global _cache_seq, _cache_result
    with _lock:
        if frame_seq >= 0 and frame_seq == _cache_seq and _cache_result is not None:
            return _cache_result
    lmk = _get_landmarker()
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
    result = lmk.detect(mp_img)
    with _lock:
        if frame_seq >= 0:
            _cache_seq    = frame_seq
        _cache_result = result
    return result


def detect_bgr(bgr_frame, frame_seq: int = -1) -> "_mp_vis.FaceLandmarkerResult":
    """Run face landmark detection on a BGR frame (standard OpenCV format).
    Thread-safe caching via frame_seq counter."""
    global _cache_seq, _cache_result
    with _lock:
        if frame_seq >= 0 and frame_seq == _cache_seq and _cache_result is not None:
            return _cache_result
    rgb    = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
    lmk    = _get_landmarker()
    mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    result = lmk.detect(mp_img)
    with _lock:
        if frame_seq >= 0:
            _cache_seq    = frame_seq
        _cache_result = result
    return result


class FaceLandmarker:
    """Compatibility wrapper around the shared singleton landmarker helpers."""

    def __init__(self):
        _get_landmarker()

    def detect(self, rgb_frame, frame_seq=-1):
        return detect(rgb_frame, frame_seq)

    def detect_bgr(self, bgr_frame, frame_seq=-1):
        return detect_bgr(bgr_frame, frame_seq)

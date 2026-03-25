"""
VERA - Environment Detector (Production v6 — ONNX Runtime)

FIXES v6:
  1. Partial object detection — lowered thresholds significantly and added
     a "partial object" mode: when a bbox touches/overlaps the frame edge,
     it is treated as a partially-visible object and confirmed with a lower
     confidence bar. Real phones half-visible at frame edges are now caught.
  2. Temporal smoothing window increased 6→10 frames; confirmation lowered
     from >=2 to >=2 but partial-edge objects only need 1 confirm (they're
     unlikely to be false positives when they're at the frame boundary).
  3. High-confidence threshold lowered from 0.55→0.40 so that partially
     occluded phones/books still trigger immediate confirmation.
  4. Added a "ghost frame" prevention: if no frames arrive for >2s the
     recent window is partially cleared to prevent stale old flags.
"""

import os
import cv2
import numpy as np
import threading
import time
import logging
from collections import deque

try:
    import onnxruntime as ort
    _has_ort = True
except ImportError:
    _has_ort = False

logger = logging.getLogger(__name__)

COCO_CLASSES_OF_INTEREST = {
    63: 'laptop',
    67: 'cell phone',
    73: 'book',
    64: 'mouse',
    66: 'keyboard',
    74: 'clock',
    26: 'handbag',
    25: 'backpack',
}

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODEL_CANDIDATES = [
    os.path.join(os.path.dirname(__file__), 'models', 'yolov8s.onnx'),
    os.path.join(_BASE_DIR, 'yolov8s.onnx'),
]
MODEL_PATH = None
for _p in _MODEL_CANDIDATES:
    if os.path.exists(_p):
        MODEL_PATH = _p
        break
if MODEL_PATH is None:
    MODEL_PATH = _MODEL_CANDIDATES[0]

# ── FIX: Lowered confidence thresholds for better partial-object detection ──
# Original: cell phone 0.22, laptop 0.24, book 0.26 — these were too high for
# half-visible objects. YOLOv8 confidence on a 50%-occluded phone is ~0.15-0.20.
CONFIDENCE_THRESHOLD = 0.18      # Base threshold (was 0.30)
NMS_IOU_THRESHOLD = 0.45

CLASS_THRESHOLDS = {
    'cell phone': 0.15,   # was 0.22 — catches half-visible phones at edges
    'laptop':     0.18,   # was 0.24
    'book':       0.17,   # was 0.26
}

# FIX: Separate lower thresholds for objects at frame edges (partially visible)
EDGE_CLASS_THRESHOLDS = {
    'cell phone': 0.12,
    'laptop':     0.14,
    'book':       0.13,
}

UNAUTHORIZED_CLASSES = {'cell phone', 'laptop', 'book'}

# FIX: Larger temporal smoothing window for stability
_TEMPORAL_WINDOW = 10            # was 6
_CONFIRM_FRAMES  = 2             # still need 2 frames to confirm
_EDGE_CONFIRM_FRAMES = 1         # edge/partial objects: only need 1 frame
_IMMEDIATE_CONF  = 0.40          # was 0.55 — immediate confirm threshold
_EDGE_MARGIN_PX  = 30            # pixels from frame edge = "partial" detection


class EnvironmentDetector:
    def __init__(self):
        self._lock = threading.Lock()
        self._result = {'objects_detected': [], 'flag': False, 'objects': [], 'unauthorized': []}
        self._has_onnx = False
        self._recent_unauthorized = deque(maxlen=_TEMPORAL_WINDOW)
        self._last_frame_ts = 0.0

        # Background thread state
        self._bg_frame = None
        self._bg_lock = threading.Lock()
        self._bg_event = threading.Event()
        self._bg_running = True
        self._frame_w = 640
        self._frame_h = 480

        if not _has_ort:
            logger.warning(
                "onnxruntime not installed. Environment detection disabled. "
                "Run: pip install onnxruntime"
            )
        elif not os.path.exists(MODEL_PATH):
            logger.warning(
                f"YOLOv8 ONNX model not found at {MODEL_PATH}. "
                "Environment detection disabled."
            )
        else:
            try:
                self.session = ort.InferenceSession(
                    MODEL_PATH,
                    providers=['CPUExecutionProvider']
                )
                self.input_name = self.session.get_inputs()[0].name
                self._has_onnx = True
                logger.info("EnvironmentDetector: YOLOv8 ONNX loaded successfully.")
            except Exception as e:
                logger.error(f"EnvironmentDetector: Failed to load ONNX model: {e}")

        self._bg_thread = threading.Thread(target=self._bg_worker, daemon=True)
        self._bg_thread.start()

    def _is_at_edge(self, bbox: list, frame_w: int, frame_h: int) -> bool:
        """
        Returns True if bbox touches or extends to/beyond the frame edge.
        This indicates a partially-visible object (e.g. phone being held
        at the bottom/side of frame — very common exam cheating pattern).
        """
        x1, y1, x2, y2 = bbox
        return (
            x1 <= _EDGE_MARGIN_PX or
            y1 <= _EDGE_MARGIN_PX or
            x2 >= frame_w - _EDGE_MARGIN_PX or
            y2 >= frame_h - _EDGE_MARGIN_PX
        )

    def _bg_worker(self):
        while self._bg_running:
            self._bg_event.wait(timeout=2.0)
            self._bg_event.clear()

            with self._bg_lock:
                frame = self._bg_frame
                self._bg_frame = None

            if frame is None or not self._has_onnx:
                continue

            result = self.analyze(frame)
            with self._lock:
                self._result = result

    def _preprocess(self, frame):
        img = cv2.resize(frame, (640, 640))
        img = img.astype(np.float32) / 255.0
        img = img.transpose(2, 0, 1)
        img = img[np.newaxis, ...]
        return img

    def _nms(self, detections):
        if not detections:
            return detections
        filtered = []
        by_class = {}
        for d in detections:
            by_class.setdefault(d['class'], []).append(d)

        for _, class_dets in by_class.items():
            boxes  = np.array([d['bbox'] for d in class_dets], dtype=np.float32)
            scores = np.array([d['confidence'] for d in class_dets], dtype=np.float32)
            x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
            areas  = (x2 - x1) * (y2 - y1)
            order  = scores.argsort()[::-1]
            keep   = []
            while order.size > 0:
                i = order[0]
                keep.append(i)
                if order.size == 1:
                    break
                xx1 = np.maximum(x1[i], x1[order[1:]])
                yy1 = np.maximum(y1[i], y1[order[1:]])
                xx2 = np.minimum(x2[i], x2[order[1:]])
                yy2 = np.minimum(y2[i], y2[order[1:]])
                w   = np.maximum(0.0, xx2 - xx1)
                h   = np.maximum(0.0, yy2 - yy1)
                inter = w * h
                iou   = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
                inds  = np.where(iou <= NMS_IOU_THRESHOLD)[0]
                order = order[inds + 1]
            filtered.extend(class_dets[i] for i in keep)

        filtered.sort(key=lambda d: d['confidence'], reverse=True)
        return filtered

    def _postprocess(self, outputs, orig_h, orig_w):
        """
        Parse YOLOv8 ONNX output.
        FIX: now tags each detection as 'at_edge' for partial-object logic.
        FIX: uses separate lower thresholds for edge-positioned detections.
        """
        raw = outputs[0][0]
        raw = raw.T

        detected = []
        for row in raw:
            class_scores = row[4:]
            class_id     = int(np.argmax(class_scores))
            confidence   = float(class_scores[class_id])

            if class_id not in COCO_CLASSES_OF_INTEREST:
                continue

            class_name = COCO_CLASSES_OF_INTEREST[class_id]

            cx, cy, w, h = row[0], row[1], row[2], row[3]
            x1 = int((cx - w / 2) * orig_w / 640)
            y1 = int((cy - h / 2) * orig_h / 640)
            x2 = int((cx + w / 2) * orig_w / 640)
            y2 = int((cy + h / 2) * orig_h / 640)

            at_edge = self._is_at_edge([x1, y1, x2, y2], orig_w, orig_h)

            # FIX: use lower thresholds for edge objects (partial visibility)
            if at_edge:
                cls_thr = EDGE_CLASS_THRESHOLDS.get(class_name, CONFIDENCE_THRESHOLD * 0.7)
            else:
                cls_thr = CLASS_THRESHOLDS.get(class_name, CONFIDENCE_THRESHOLD)

            if confidence < cls_thr:
                continue

            detected.append({
                'class':      class_name,
                'confidence': round(confidence, 3),
                'bbox':       [x1, y1, x2, y2],
                'at_edge':    at_edge,
            })

        detected = self._nms(detected)
        return detected

    def analyze(self, frame):
        """Run ONNX inference. Returns detection dict with enhanced partial-object logic."""
        if not self._has_onnx:
            return {'objects_detected': [], 'flag': False, 'objects': [], 'unauthorized': []}

        orig_h, orig_w = frame.shape[:2]
        self._frame_h = orig_h
        self._frame_w = orig_w

        inp     = self._preprocess(frame)
        outputs = self.session.run(None, {self.input_name: inp})
        detected = self._postprocess(outputs, orig_h, orig_w)

        object_names   = [d['class'] for d in detected]
        unauthorized_now = [d['class'] for d in detected if d['class'] in UNAUTHORIZED_CLASSES]

        self._recent_unauthorized.append(set(unauthorized_now))

        # FIX: Ghost-frame prevention — if window is old, decay it
        now = time.monotonic()
        if self._last_frame_ts > 0 and (now - self._last_frame_ts) > 3.0:
            # Clear half the window to avoid stale positives
            half = len(self._recent_unauthorized) // 2
            for _ in range(half):
                if self._recent_unauthorized:
                    self._recent_unauthorized.popleft()
        self._last_frame_ts = now

        # Count how many frames each object appeared in
        counts = {}
        for s in self._recent_unauthorized:
            for name in s:
                counts[name] = counts.get(name, 0) + 1

        # FIX: separate confirm thresholds for edge vs center objects
        edge_dets_classes = {d['class'] for d in detected if d.get('at_edge') and d['class'] in UNAUTHORIZED_CLASSES}

        unauthorized_confirmed = []
        for name, c in counts.items():
            if name in edge_dets_classes:
                # Edge/partial objects — lower bar to confirm
                if c >= _EDGE_CONFIRM_FRAMES:
                    unauthorized_confirmed.append(name)
            else:
                if c >= _CONFIRM_FRAMES:
                    unauthorized_confirmed.append(name)

        # FIX: lower immediate-confirm threshold to 0.40 (was 0.55)
        high_conf_now = [
            d['class'] for d in detected
            if d['class'] in UNAUTHORIZED_CLASSES and d['confidence'] >= _IMMEDIATE_CONF
        ]

        # Also immediately confirm any edge detection above a lower bar
        edge_immediate = [
            d['class'] for d in detected
            if d['class'] in UNAUTHORIZED_CLASSES
            and d.get('at_edge')
            and d['confidence'] >= 0.25
        ]

        unauthorized = sorted(set(unauthorized_confirmed + high_conf_now + edge_immediate))

        return {
            'objects_detected':  detected,
            'flag':              len(unauthorized) > 0,
            'flag_reason':       unauthorized if unauthorized else [],
            'objects':           object_names,
            'unauthorized':      unauthorized,
            'unauthorized_now':  unauthorized_now,
            'partial_detections': [d for d in detected if d.get('at_edge') and d['class'] in UNAUTHORIZED_CLASSES],
        }

    def check(self, frame=None):
        """Called by pipeline. Submits frame to bg thread, returns last result instantly."""
        if frame is not None:
            with self._bg_lock:
                self._bg_frame = frame.copy()
                self._bg_event.set()

        with self._lock:
            return dict(self._result)

    def shutdown(self):
        self._bg_running = False
        self._bg_event.set()

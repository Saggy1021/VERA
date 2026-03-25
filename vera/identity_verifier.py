"""
VERA — Identity Verifier (InsightFace ArcFace + MiniFASNet Liveness)
Enroll a candidate's face during setup, verify on every pipeline tick.
All models are MIT / Apache 2.0 licensed.
"""
import os
import numpy as np
import cv2
import threading
import logging

try:
    import onnxruntime as ort
    _has_ort = True
except ImportError:
    _has_ort = False

logger = logging.getLogger(__name__)

MINIFASNET_MODEL_PATH = os.path.join(
    os.path.dirname(__file__),
    'models', 'MiniFASNet',
    '2.7_80x80_MiniFASNetV2.onnx'
)
COSINE_THRESHOLD = 0.4   # Below this = identity mismatch
ENROLL_DET_THRESHOLD = 0.35

try:
    import insightface
    from insightface.app import FaceAnalysis
    _has_insightface = True
except ImportError:
    _has_insightface = False
    logger.warning("insightface not installed. Identity verification disabled.")


class IdentityVerifier:
    """
    Provides face enrollment + verification + liveness detection.
    Enrollment happens once during the setup wizard.
    Verification runs every pipeline tick.
    """

    def __init__(self, face_app=None):
        self._lock = threading.Lock()
        self._enrolled_embedding = None
        self._ready = False

        if not _has_insightface:
            return

        try:
            if face_app is not None:
                self._app = face_app
            else:
                # Fallback: construct locally (used if called without singleton)
                import insightface
                self._app = insightface.app.FaceAnalysis(
                    name="buffalo_sc",
                    providers=["CPUExecutionProvider"]
                )
                self._app.prepare(ctx_id=-1, det_thresh=ENROLL_DET_THRESHOLD, det_size=(640, 640))
            self._ready = True
            logger.info("IdentityVerifier: InsightFace loaded.")
        except Exception as e:
            logger.error(f"IdentityVerifier: InsightFace init failed: {e}")

        # Load MiniFASNet liveness model
        self._liveness_session = None
        if _has_ort and os.path.exists(MINIFASNET_MODEL_PATH):
            try:
                self._liveness_session = ort.InferenceSession(
                    MINIFASNET_MODEL_PATH,
                    providers=['CPUExecutionProvider']
                )
                logger.info("IdentityVerifier: MiniFASNet liveness model loaded.")
            except Exception as e:
                logger.debug(f"IdentityVerifier: Liveness model failed: {e}")
        else:
            logger.debug(
                f"MiniFASNet model not found at {MINIFASNET_MODEL_PATH}. "
                "Run MANUAL STEP 2 from the implementation plan."
            )

    def enroll(self, frame: np.ndarray) -> dict:
        """
        Extract and store a face embedding from the enrollment frame.
        Call this once during the setup wizard after the candidate is seated.
        Returns: {'success': bool, 'message': str}
        """
        if not self._ready:
            return {'success': False, 'message': 'InsightFace not available.'}

        faces = self._detect_faces(frame)
        if not faces:
            return {
                'success': False,
                'message': 'No face detected in enrollment frame. Move closer, face the camera, and improve lighting.'
            }
        if len(faces) > 1:
            return {'success': False, 'message': 'Multiple faces detected. Ensure only one person is visible.'}

        with self._lock:
            self._enrolled_embedding = faces[0].embedding.copy()

        logger.info("IdentityVerifier: Candidate enrolled successfully.")
        return {'success': True, 'message': 'Identity enrolled.'}

    def _detect_faces(self, frame: np.ndarray) -> list:
        """Robust detector wrapper for webcam enrollment frames."""
        # Pass 1: raw frame
        faces = self._app.get(frame)
        if faces:
            return faces

        # Pass 2: upsample tiny inputs; low-res webcams are common on laptops.
        h, w = frame.shape[:2]
        min_side = min(h, w)
        if min_side > 0 and min_side < 640:
            scale = 640.0 / float(min_side)
            up = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
            faces = self._app.get(up)
            if faces:
                return faces

        # Pass 3: contrast enhancement for dim rooms.
        try:
            ycrcb = cv2.cvtColor(frame, cv2.COLOR_BGR2YCrCb)
            y, cr, cb = cv2.split(ycrcb)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            y_eq = clahe.apply(y)
            enhanced = cv2.cvtColor(cv2.merge((y_eq, cr, cb)), cv2.COLOR_YCrCb2BGR)
            faces = self._app.get(enhanced)
            if faces:
                return faces
        except Exception as e:
            logger.debug(f"IdentityVerifier: fallback preprocessing failed: {e}")

        return []

    def verify(self, frame: np.ndarray) -> dict:
        """
        Compare the face in the current frame against the enrolled embedding.
        Returns: {'verified': bool, 'similarity': float, 'mismatch': bool,
                  'liveness': bool, 'no_face': bool}
        """
        if not self._ready:
            return {'verified': True, 'similarity': 1.0, 'mismatch': False,
                    'liveness': True, 'no_face': False}

        faces = self._app.get(frame)
        if not faces:
            return {'verified': False, 'similarity': 0.0, 'mismatch': False,
                    'liveness': True, 'no_face': True}

        face = faces[0]   # Use the most prominent face
        current_embedding = face.embedding

        with self._lock:
            if self._enrolled_embedding is None:
                return {'verified': True, 'similarity': 1.0, 'mismatch': False,
                        'liveness': True, 'no_face': False}

            # Cosine similarity
            similarity = float(
                np.dot(self._enrolled_embedding, current_embedding) /
                (np.linalg.norm(self._enrolled_embedding) * np.linalg.norm(current_embedding))
            )

        mismatch = similarity < COSINE_THRESHOLD

        # Liveness check
        liveness = self._check_liveness(frame, face)

        return {
            'verified': not mismatch and liveness,
            'similarity': round(similarity, 4),
            'mismatch': mismatch,
            'liveness': liveness,
            'no_face': False
        }

    def _check_liveness(self, frame: np.ndarray, face) -> bool:
        """Run MiniFASNet liveness check. Returns True if live, False if spoof."""
        if self._liveness_session is None:
            return True   # Degrade gracefully if model not loaded

        try:
            bbox = face.bbox.astype(int)
            x1, y1, x2, y2 = bbox[0], bbox[1], bbox[2], bbox[3]
            face_crop = frame[max(0, y1):y2, max(0, x1):x2]
            if face_crop.size == 0:
                return True

            face_crop = cv2.resize(face_crop, (80, 80))
            face_crop = face_crop.astype(np.float32) / 255.0
            face_crop = face_crop.transpose(2, 0, 1)[np.newaxis]

            input_name = self._liveness_session.get_inputs()[0].name
            outputs = self._liveness_session.run(None, {input_name: face_crop})
            # Output index 1 = live probability
            live_prob = float(outputs[0][0][1])
            return live_prob > 0.5
        except Exception as e:
            logger.debug(f"Liveness check error (non-critical): {e}")
            return True

    def reset(self):
        """Clear enrolled embedding at session end."""
        with self._lock:
            self._enrolled_embedding = None

    def is_enrolled(self) -> bool:
        """Return True when a reference embedding exists for verification."""
        with self._lock:
            return self._enrolled_embedding is not None

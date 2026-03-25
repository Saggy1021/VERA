"""
VERA — Session Recorder (Rolling Buffer + MinIO Evidence Upload)
Maintains a 30-second frame buffer. On HIGH severity confirmation,
extracts an evidence clip and uploads to MinIO for proctor review.
"""
import os
import time
import logging
import tempfile
from collections import deque

import numpy as np
import cv2

try:
    import boto3
    from botocore.exceptions import ClientError
    _has_boto3 = True
except ImportError:
    _has_boto3 = False

logger = logging.getLogger(__name__)

BUFFER_SECONDS = 30
FPS = 10                      # Assumed pipeline frame rate
BUFFER_MAXLEN = BUFFER_SECONDS * FPS
MINIO_ENDPOINT = os.getenv('MINIO_ENDPOINT', 'http://localhost:9000')
MINIO_ACCESS_KEY = os.getenv('MINIO_ACCESS_KEY', 'vera')
MINIO_SECRET_KEY = os.getenv('MINIO_SECRET_KEY', 'vera_secret123')
EVIDENCE_BUCKET = 'evidence-clips'


class SessionRecorder:
    """
    Rolling frame buffer + evidence clip extraction.
    Frames are stored as JPEG bytes to minimize memory usage.
    A 30s buffer at 10fps uses ~30MB (1 frame ~ 100KB JPEG).
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._buffer = deque(maxlen=BUFFER_MAXLEN)
        self._s3 = None

        if _has_boto3:
            try:
                self._s3 = boto3.client(
                    's3',
                    endpoint_url=MINIO_ENDPOINT,
                    aws_access_key_id=MINIO_ACCESS_KEY,
                    aws_secret_access_key=MINIO_SECRET_KEY
                )
                self._ensure_bucket()
            except Exception as e:
                logger.debug(f"SessionRecorder: Could not connect to MinIO: {e}")
                self._s3 = None
        else:
            logger.warning("SessionRecorder: boto3 not installed. Evidence upload disabled.")

    def _ensure_bucket(self):
        if self._s3 is None:
            return
        try:
            self._s3.head_bucket(Bucket=EVIDENCE_BUCKET)
        except Exception:
            try:
                self._s3.create_bucket(Bucket=EVIDENCE_BUCKET)
                logger.info(f"SessionRecorder: Created bucket {EVIDENCE_BUCKET}")
            except Exception as e:
                logger.debug(f"SessionRecorder: Could not create bucket: {e}")

    def add_frame(self, frame: np.ndarray):
        """Add a BGR numpy frame to the rolling buffer."""
        _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        self._buffer.append({
            'ts': time.monotonic(),
            'data': jpeg.tobytes()
        })

    def extract_evidence_clip(self, flag_name: str):
        """
        Export current buffer as an MP4 and upload to MinIO.
        Returns the MinIO object key, or None on failure.
        """
        if not self._buffer:
            return None

        timestamp = int(time.time())
        key = f"{self.session_id}/{timestamp}_{flag_name}.mp4"
        tmp_path = os.path.join(tempfile.gettempdir(), f"vera_evidence_{self.session_id}_{timestamp}.mp4")

        try:
            frames = list(self._buffer)
            first_img = cv2.imdecode(
                np.frombuffer(frames[0]['data'], np.uint8),
                cv2.IMREAD_COLOR
            )
            h, w = first_img.shape[:2]

            writer = cv2.VideoWriter(
                tmp_path,
                cv2.VideoWriter_fourcc(*'mp4v'),
                FPS, (w, h)
            )
            for f in frames:
                img = cv2.imdecode(np.frombuffer(f['data'], np.uint8), cv2.IMREAD_COLOR)
                writer.write(img)
            writer.release()

            if self._s3:
                self._s3.upload_file(tmp_path, EVIDENCE_BUCKET, key)
                logger.info(f"SessionRecorder: Evidence clip uploaded -> {key}")
            else:
                logger.info(f"SessionRecorder: Evidence clip saved locally -> {tmp_path}")
                return tmp_path

            os.unlink(tmp_path)
            return key
        except Exception as e:
            logger.error(f"SessionRecorder: Failed to save evidence clip: {e}")
            return None

    def reset(self):
        self._buffer.clear()

"""
One-shot module rewriter for VERA v2.
Run: python _write_modules.py
"""
import os

BASE = os.path.dirname(os.path.abspath(__file__))

# ─────────────────────────────────────────────────────────────────────────────
BEHAVIORAL = '''\
"""
VERA - Behavioral Analyzer (Production v2)
MediaPipe Face Mesh 468 landmarks — no training needed.
Outputs: Eye gaze direction, blink rate (EAR), head pose (solvePnP),
         eye contact, all with temporal smoothing.
"""
import cv2
import numpy as np
import mediapipe as mp
import time
from collections import deque, Counter

# ── Landmark indices --------------------------------------------------------
L_EYE_TOP, L_EYE_BOT = 159, 145
L_EYE_OUT, L_EYE_INN = 33,  133
R_EYE_TOP, R_EYE_BOT = 386, 374
R_EYE_OUT, R_EYE_INN = 362, 263
L_IRIS, R_IRIS        = 468, 473
NOSE_TIP, CHIN        = 4,   152
L_MOUTH, R_MOUTH      = 61,  291

BLINK_EAR_THRESH = 0.21
BLINK_CONSEC     = 2
BLINK_WIN_SEC    = 60
GAZE_SMOOTH_N    = 8

GAZE_MEANING = {
    "upper_right": {"meaning": "Constructing visuals",   "risk": 0.40, "note": "Possible fabrication"},
    "upper_left":  {"meaning": "Recalling visuals",      "risk": 0.10, "note": "Accessing visual memory"},
    "right":       {"meaning": "Constructing audio",     "risk": 0.35, "note": "Constructing inner voice"},
    "left":        {"meaning": "Recalling audio",        "risk": 0.10, "note": "Remembering sounds"},
    "lower_right": {"meaning": "Internal dialogue",      "risk": 0.20, "note": "Self-talk"},
    "lower_left":  {"meaning": "Accessing feelings",     "risk": 0.15, "note": "Emotional memory"},
    "center":      {"meaning": "Direct engagement",      "risk": 0.05, "note": "Focused attention"},
    "down":        {"meaning": "Avoidance / processing", "risk": 0.25, "note": "Looking away"},
}

# 3-D model points (mm) for solvePnP — generic face model
_MODEL_3D = np.array([
    (0.0,    0.0,    0.0  ),   # Nose tip
    (0.0,  -330.0,  -65.0),   # Chin
    (-225.0, 170.0, -135.0),   # Left eye outer
    ( 225.0, 170.0, -135.0),   # Right eye outer
    (-150.0,-150.0, -125.0),   # Left mouth
    ( 150.0,-150.0, -125.0),   # Right mouth
], dtype=np.float64)


class BehavioralAnalyzer:
    def __init__(self):
        mp_fm = mp.solutions.face_mesh
        self.face_mesh = mp_fm.FaceMesh(
            static_image_mode=False,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._blink_count    = 0
        self._eye_closed_frm = 0
        self._blink_times    = deque()
        self._gaze_hist      = deque(maxlen=GAZE_SMOOTH_N)
        self._yaw_hist       = deque(maxlen=12)
        self._last_result    = None

    # ── Public API ─────────────────────────────────────────────────────────
    def analyze(self, frame: np.ndarray) -> dict:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = self.face_mesh.process(rgb)
        if not res.multi_face_landmarks:
            return self._empty()

        lm = res.multi_face_landmarks[0].landmark
        h, w = frame.shape[:2]

        gaze      = self._compute_gaze(lm, w, h)
        blink     = self._compute_blink(lm, w, h)
        head      = self._compute_head_pose(lm, w, h)
        eye_cont  = self._compute_eye_contact(lm)

        # Temporal smoothing on gaze
        self._gaze_hist.append(gaze["direction"])
        smooth_gaze = Counter(self._gaze_hist).most_common(1)[0][0]
        gaze["direction"] = smooth_gaze

        # Rolling head yaw
        self._yaw_hist.append(abs(head["yaw"]))
        avg_yaw = float(np.mean(self._yaw_hist))

        blink_risk = min(max(blink["rate"] - 20, 0) / 30, 1.0) * 0.55 if blink["rate"] > 20 else 0.0
        gaze_risk  = GAZE_MEANING.get(smooth_gaze, GAZE_MEANING["center"])["risk"]
        head_risk  = min(avg_yaw / 45.0, 1.0) * 0.35

        result = {
            "gaze":               gaze,
            "blink":              blink,
            "head_pose":          head,
            "eye_contact":        eye_cont,
            "gaze_interpretation":GAZE_MEANING.get(smooth_gaze, GAZE_MEANING["center"]),
            "blink_risk":         round(blink_risk, 3),
            "gaze_risk":          round(gaze_risk,  3),
            "head_risk":          round(head_risk,   3),
            "landmarks":          lm,
            "frame_shape":        frame.shape,
        }
        self._last_result = result
        return result

    def draw_overlays(self, frame: np.ndarray, data: dict) -> np.ndarray:
        if data.get("landmarks") is None:
            return frame
        lm  = data["landmarks"]
        h, w = frame.shape[:2]
        def px(i): return (int(lm[i].x * w), int(lm[i].y * h))

        for idx in [L_EYE_TOP, L_EYE_BOT, L_EYE_OUT, L_EYE_INN,
                    R_EYE_TOP, R_EYE_BOT, R_EYE_OUT, R_EYE_INN]:
            cv2.circle(frame, px(idx), 2, (0, 255, 255), -1)

        if len(lm) > 473:
            cv2.circle(frame, px(L_IRIS), 3, (0, 200, 255), -1)
            cv2.circle(frame, px(R_IRIS), 3, (0, 200, 255), -1)

        gd = data["gaze"]["direction"]
        br = data["blink"]["rate"]
        hd = data["head_pose"]["direction"]
        bc = (0, 100, 255) if data["blink"]["elevated"] else (0, 255, 0)
        hc = (0, 0,   255) if data["head_pose"]["is_turned"] else (0, 255, 0)

        cv2.putText(frame, f"Gaze: {gd}",        (8, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 1)
        cv2.putText(frame, f"Blink: {br}/min",   (8, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.55, bc,           1)
        cv2.putText(frame, f"Head: {hd}",         (8, 72), cv2.FONT_HERSHEY_SIMPLEX, 0.55, hc,           1)
        return frame

    # ── Internal helpers ───────────────────────────────────────────────────
    def _px(self, lm, idx, w, h):
        return np.array([lm[idx].x * w, lm[idx].y * h])

    def _compute_gaze(self, lm, w, h):
        px = lambda i: self._px(lm, i, w, h)
        has_iris = len(lm) > 473

        li = px(L_IRIS) if has_iris else (px(L_EYE_OUT) + px(L_EYE_INN)) / 2
        ri = px(R_IRIS) if has_iris else (px(R_EYE_OUT) + px(R_EYE_INN)) / 2

        def h_ratio(iris, outer, inner):
            denom = max(inner[0] - outer[0], 1e-6)
            return (iris[0] - outer[0]) / denom

        def v_ratio(iris, top, bot):
            denom = max(bot[1] - top[1], 1e-6)
            return (iris[1] - top[1]) / denom

        lhr = h_ratio(li, px(L_EYE_OUT), px(L_EYE_INN))
        rhr = h_ratio(ri, px(R_EYE_OUT), px(R_EYE_INN))
        lvr = v_ratio(li, px(L_EYE_TOP), px(L_EYE_BOT))
        rvr = v_ratio(ri, px(R_EYE_TOP), px(R_EYE_BOT))

        h_val = (lhr + rhr) / 2.0
        v_val = (lvr + rvr) / 2.0

        hd = "right"  if h_val > 0.62 else ("left"  if h_val < 0.38 else "center")
        vd = "upper"  if v_val < 0.33 else ("lower" if v_val > 0.67 else "center")

        DIR_MAP = {
            ("upper", "right"):  "upper_right",
            ("upper", "left"):   "upper_left",
            ("upper", "center"): "upper_right",
            ("lower", "right"):  "lower_right",
            ("lower", "left"):   "lower_left",
            ("lower", "center"): "down",
            ("center","right"):  "right",
            ("center","left"):   "left",
            ("center","center"): "center",
        }
        direction = DIR_MAP.get((vd, hd), "center")
        return {"direction": direction, "h_ratio": round(h_val, 3), "v_ratio": round(v_val, 3)}

    def _ear(self, lm, top, bot, out, inn, w, h):
        px = lambda i: self._px(lm, i, w, h)
        vert = np.linalg.norm(px(top) - px(bot))
        horiz = np.linalg.norm(px(out) - px(inn))
        return vert / max(horiz, 1e-6)

    def _compute_blink(self, lm, w, h):
        le = self._ear(lm, L_EYE_TOP, L_EYE_BOT, L_EYE_OUT, L_EYE_INN, w, h)
        re = self._ear(lm, R_EYE_TOP, R_EYE_BOT, R_EYE_OUT, R_EYE_INN, w, h)
        avg = (le + re) / 2.0
        closed = avg < BLINK_EAR_THRESH
        now = time.time()

        if closed:
            self._eye_closed_frm += 1
        else:
            if self._eye_closed_frm >= BLINK_CONSEC:
                self._blink_count += 1
                self._blink_times.append(now)
            self._eye_closed_frm = 0

        while self._blink_times and now - self._blink_times[0] > BLINK_WIN_SEC:
            self._blink_times.popleft()

        n = len(self._blink_times)
        elapsed = (now - self._blink_times[0]) if n > 0 else BLINK_WIN_SEC
        rate = (n / max(elapsed, 1)) * 60
        return {
            "total":    self._blink_count,
            "rate":     round(rate, 1),
            "ear":      round(avg, 3),
            "closed":   closed,
            "elevated": rate > 25,
        }

    def _compute_head_pose(self, lm, w, h):
        def px2d(i): return [lm[i].x * w, lm[i].y * h]
        img_pts = np.array([
            px2d(NOSE_TIP), px2d(CHIN),
            px2d(L_EYE_OUT), px2d(R_EYE_OUT),
            px2d(L_MOUTH),  px2d(R_MOUTH),
        ], dtype=np.float64)

        focal  = w
        cam_mat = np.array([[focal, 0, w/2], [0, focal, h/2], [0, 0, 1]], dtype=np.float64)
        dist   = np.zeros((4, 1))

        try:
            _, rvec, _ = cv2.solvePnP(_MODEL_3D, img_pts, cam_mat, dist,
                                      flags=cv2.SOLVEPNP_ITERATIVE)
            rmat, _    = cv2.Rodrigues(rvec)
            proj_mat   = np.hstack((rmat, np.zeros((3, 1))))
            _, _, _, _, _, _, eu = cv2.decomposeProjectionMatrix(proj_mat)
            pitch, yaw, roll = float(eu[0]), float(eu[1]), float(eu[2])
        except Exception:
            pitch = yaw = roll = 0.0

        direction = "Forward"
        if   yaw   >  20: direction = "Right"
        elif yaw   < -20: direction = "Left"
        elif pitch < -20: direction = "Down"
        elif pitch >  20: direction = "Up"

        return {
            "yaw":       round(yaw,   1),
            "pitch":     round(pitch, 1),
            "roll":      round(roll,  1),
            "direction": direction,
            "is_turned": abs(yaw) > 20 or abs(pitch) > 20,
        }

    def _compute_eye_contact(self, lm):
        nx  = lm[NOSE_TIP].x
        emx = (lm[L_EYE_OUT].x + lm[R_EYE_OUT].x) / 2
        diff = abs(nx - emx)
        return {"making_contact": diff < 0.05, "diff": round(diff, 4)}

    def _empty(self):
        return {
            "gaze":                {"direction": "unknown", "h_ratio": 0.5, "v_ratio": 0.5},
            "blink":               {"total": 0, "rate": 0, "ear": 0, "closed": False, "elevated": False},
            "head_pose":           {"yaw": 0, "pitch": 0, "roll": 0, "direction": "Unknown", "is_turned": False},
            "eye_contact":         {"making_contact": False, "diff": 0},
            "gaze_interpretation": GAZE_MEANING["center"],
            "blink_risk":          0.0,
            "gaze_risk":           0.0,
            "head_risk":           0.0,
            "landmarks":           None,
            "frame_shape":         (480, 640, 3),
        }
'''

# ─────────────────────────────────────────────────────────────────────────────
AUDIO = '''\
"""
VERA - Audio Analyzer (Production v2)
OpenAI Whisper "base.en" for English STT.
Sync score = 55% char similarity + 45% word Jaccard overlap.
Whisper model cached as class variable — loaded only once.
"""
import time
from difflib import SequenceMatcher


class AudioAnalyzer:
    _model_cache: dict = {}

    def __init__(self, model_size: str = "base.en"):
        self._model_size = model_size
        self._model      = None
        self._load()

    # ── Lazy load (one per model_size) ──────────────────────────────────────
    def _load(self):
        if self._model_size in AudioAnalyzer._model_cache:
            self._model = AudioAnalyzer._model_cache[self._model_size]
            return
        try:
            import whisper
            print(f"[AudioAnalyzer] Loading Whisper '{self._model_size}' …")
            m = whisper.load_model(self._model_size)
            AudioAnalyzer._model_cache[self._model_size] = m
            self._model = m
            print("[AudioAnalyzer] Whisper ready.")
        except Exception as exc:
            self._model = None
            print(f"[AudioAnalyzer] Whisper load failed: {exc}")

    # ── Public API ───────────────────────────────────────────────────────────
    def transcribe_file(self, path: str) -> dict:
        """Transcribe an audio/video file with Whisper."""
        if self._model is None:
            return {"text": "", "segments": [], "duration": 0, "error": "Whisper not loaded"}
        try:
            t0 = time.time()
            result = self._model.transcribe(
                path,
                fp16=False,
                language="en",
                condition_on_previous_text=False,
            )
            return {
                "text":     result["text"].strip(),
                "segments": result.get("segments", []),
                "duration": round(time.time() - t0, 2),
                "error":    None,
            }
        except Exception as exc:
            return {"text": "", "segments": [], "duration": 0, "error": str(exc)}

    def compute_sync_score(self, lip_text: str, audio_text: str) -> dict:
        """
        Returns a dict with:
          score          : 0–1 (1 = perfect sync)
          is_synced      : bool
          risk           : 0–1 deception risk from mismatch
          char_similarity: char-level ratio
          word_overlap   : Jaccard on words
          verdict        : human-readable string
        """
        if not lip_text or not audio_text:
            return {
                "score": 1.0, "is_synced": True, "risk": 0.0,
                "char_similarity": 1.0, "word_overlap": 1.0,
                "lip_text": lip_text, "audio_text": audio_text,
                "verdict": "Insufficient data for comparison",
            }

        lc = lip_text.strip().lower()
        ac = audio_text.strip().lower()

        char_sim = SequenceMatcher(None, lc, ac).ratio()

        lw = set(lc.split())
        aw = set(ac.split())
        jacc = len(lw & aw) / max(len(lw | aw), 1)

        score = round(char_sim * 0.55 + jacc * 0.45, 3)
        risk  = round(max(0.0, (0.50 - score) / 0.50) * 0.85, 3) if score < 0.50 else 0.0

        return {
            "score":          score,
            "is_synced":      score >= 0.45,
            "risk":           risk,
            "char_similarity":round(char_sim, 3),
            "word_overlap":   round(jacc,     3),
            "lip_text":       lip_text,
            "audio_text":     audio_text,
            "verdict":        self._verdict(score),
        }

    # ── Internal ─────────────────────────────────────────────────────────────
    @staticmethod
    def _verdict(score: float) -> str:
        if score >= 0.70: return "Synced — audio matches lip movement"
        if score >= 0.45: return "Partial mismatch detected"
        if score >= 0.20: return "MISMATCH — possible external audio source"
        return "NO MATCH — likely lip-syncing or hidden earpiece"
'''

# ─────────────────────────────────────────────────────────────────────────────
DECEPTION = '''\
"""
VERA - Deception Scoring Engine (Production v2)
Pure rule-based; no ML training required.
6 weighted signals based on Ekman, FBI, Univ. Michigan research.
Temporal rolling average (30 frames) for stable output.
Context multipliers: interview / exam / interrogation / therapy.
"""
import time
from collections import deque
from dataclasses import dataclass
from typing import List


WEIGHTS = {
    "audio_visual_mismatch": 0.30,
    "deceptive_emotion":     0.22,
    "elevated_blink_rate":   0.16,
    "gaze_construction":     0.16,
    "head_turned_away":      0.10,
    "silent_lip_movement":   0.06,
}

CONTEXT_MULT = {
    "interview":    1.00,
    "exam":         1.10,
    "interrogation":1.20,
    "therapy":      0.70,
    "default":      1.00,
}

VERDICTS = [
    (20,  "LOW RISK — Behaviour appears normal",                "low"),
    (40,  "LOW-MEDIUM — Minor anomalies noted",                 "low_medium"),
    (60,  "MEDIUM — Inconclusive, monitor closely",             "medium"),
    (78,  "HIGH RISK — Multiple deception indicators present",  "high"),
    (101, "CRITICAL — Strong deception pattern detected",       "critical"),
]


@dataclass
class Signal:
    name:         str
    triggered:    bool
    contribution: float   # raw points (0–100 scale)
    reason:       str


class DeceptionScorer:
    def __init__(self, context: str = "interview"):
        self.context = context
        self.mult    = CONTEXT_MULT.get(context, 1.00)
        self._scores: deque = deque(maxlen=30)
        self._log:    List[dict] = []

    # ── Public API ───────────────────────────────────────────────────────────
    def calculate(
        self,
        emotion_data:  dict,
        behavior_data: dict,
        sync_data:     dict,
        lip_movement:  float = 0.0,
        has_audio:     bool  = True,
    ) -> dict:
        signals: List[Signal] = []

        # ── 1. Audio-visual mismatch ──────────────────────────────────────
        if has_audio:
            av_score = sync_data.get("score", 1.0)
            av_risk  = sync_data.get("risk",  0.0)
            trig     = av_score < 0.45
            signals.append(Signal(
                "audio_visual_mismatch", trig,
                av_risk * WEIGHTS["audio_visual_mismatch"] * 100,
                sync_data.get("verdict", "No audio") if trig else "Audio-lip synced",
            ))

        # ── 2. Deceptive emotion ──────────────────────────────────────────
        emo_risk = emotion_data.get("risk_score", 0.0)
        emo_trig = emotion_data.get("is_deceptive_emotion", False)
        signals.append(Signal(
            "deceptive_emotion", emo_trig,
            emo_risk * WEIGHTS["deceptive_emotion"] * 100,
            f"Emotion: {emotion_data.get('label','Unknown')} "
            f"({emotion_data.get('confidence',0):.0f}%)",
        ))

        # ── 3. Elevated blink rate ────────────────────────────────────────
        brate  = behavior_data.get("blink", {}).get("rate", 0)
        belev  = brate > 25
        brisk  = min((brate - 20) / 30, 1.0) * 0.60 if brate > 20 else 0.0
        signals.append(Signal(
            "elevated_blink_rate", belev,
            brisk * WEIGHTS["elevated_blink_rate"] * 100,
            f"Blink rate: {brate:.0f}/min ({'elevated' if belev else 'normal'}, baseline 15-20)",
        ))

        # ── 4. Gaze construction ──────────────────────────────────────────
        gdir   = behavior_data.get("gaze", {}).get("direction", "center")
        grisk  = behavior_data.get("gaze_risk", 0.0)
        gconst = gdir in ("upper_right", "right")
        gi     = behavior_data.get("gaze_interpretation", {})
        signals.append(Signal(
            "gaze_construction", gconst,
            grisk * WEIGHTS["gaze_construction"] * 100,
            f"Gaze: {gdir} — {gi.get('meaning','')}",
        ))

        # ── 5. Head turned away ───────────────────────────────────────────
        hturned= behavior_data.get("head_pose", {}).get("is_turned", False)
        hrisk  = behavior_data.get("head_risk", 0.0)
        hdir   = behavior_data.get("head_pose", {}).get("direction", "Forward")
        hyaw   = behavior_data.get("head_pose", {}).get("yaw", 0)
        signals.append(Signal(
            "head_turned_away", hturned,
            hrisk * WEIGHTS["head_turned_away"] * 100,
            f"Head {hdir} {hyaw:.0f}°" if hturned else "Head facing forward",
        ))

        # ── 6. Silent lip movement ────────────────────────────────────────
        silent = (lip_movement > 0.25) and not has_audio
        lrisk  = lip_movement * 0.50 if silent else 0.0
        signals.append(Signal(
            "silent_lip_movement", silent,
            lrisk * WEIGHTS["silent_lip_movement"] * 100,
            f"Silent mouth movement (score: {lip_movement:.3f})" if silent else "No silent mouthing",
        ))

        # ── Aggregate ─────────────────────────────────────────────────────
        raw   = sum(s.contribution for s in signals)
        final = min(raw * self.mult, 100.0)
        self._scores.append(final)
        running_avg = round(sum(self._scores) / len(self._scores), 1)

        verdict_txt, level = self._verdict(final)
        flags = [s.reason for s in signals if s.triggered]

        self._log.append({
            "time":  time.strftime("%H:%M:%S"),
            "score": round(final, 1),
            "flags": flags,
        })

        return {
            "score":          round(final, 1),
            "verdict":        verdict_txt,
            "level":          level,
            "flags":          flags,
            "triggered":      [s.name for s in signals if s.triggered],
            "all_signals":    [
                {"name": s.name, "triggered": s.triggered,
                 "contribution": round(s.contribution, 2), "reason": s.reason}
                for s in signals
            ],
            "running_average":running_avg,
            "context":        self.context,
        }

    def get_session_summary(self) -> dict:
        if not self._scores:
            return {}
        sc = list(self._scores)
        return {
            "total_frames":       len(sc),
            "average_score":      round(sum(sc) / len(sc), 1),
            "peak_score":         round(max(sc), 1),
            "time_high_risk_pct": round(sum(1 for s in sc if s >= 60) / len(sc) * 100, 1),
            "context":            self.context,
            "signal_log":         self._log[-20:],
        }

    # ── Internal ─────────────────────────────────────────────────────────────
    @staticmethod
    def _verdict(score: float):
        for threshold, text, level in VERDICTS:
            if score < threshold:
                return text, level
        return VERDICTS[-1][1], VERDICTS[-1][2]
'''

# ─────────────────────────────────────────────────────────────────────────────
PIPELINE = '''\
"""
VERA - Master Pipeline (Production v2)
Orchestrates LipNet + Emotion + Behavioral + Audio + Deception.
LipNet runs every 75 frames on MediaPipe-extracted 46×140 lip crops.
Graceful fallback if any module fails to load.
"""
import os
import sys
import cv2
import numpy as np
import time
from collections import deque

# Ensure app/ is on the path for modelutil / utils
APP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from vera.lip_extractor       import LipExtractor
from vera.emotion_detector    import EmotionDetector
from vera.behavioral_analyzer import BehavioralAnalyzer
from vera.audio_analyzer      import AudioAnalyzer
from vera.deception_scorer    import DeceptionScorer


class VERAPipeline:
    LIPNET_FRAMES        = 75
    LIPNET_H, LIPNET_W   = 46, 140

    def __init__(self, context: str = "interview", use_lipnet: bool = True):
        self.context    = context
        self.use_lipnet = use_lipnet

        print("[VERA] Initialising pipeline …")
        self.lip_ext   = LipExtractor()
        self.emotion   = EmotionDetector()
        self.behavior  = BehavioralAnalyzer()
        self.audio     = AudioAnalyzer(model_size="base.en")
        self.deception = DeceptionScorer(context=context)

        self.lipnet_model  = None
        self.num_to_char   = None
        if use_lipnet:
            self._load_lipnet()

        self._lip_buf         : deque = deque(maxlen=self.LIPNET_FRAMES)
        self._latest_lip_text : str   = ""
        self._latest_audio    : str   = ""
        self._latest_sync     : dict  = {}
        self._frame_count     : int   = 0
        self._alerts          : list  = []

        print("[VERA] Pipeline ready.")

    # ── LipNet loading ───────────────────────────────────────────────────────
    def _load_lipnet(self):
        try:
            from modelutil import load_model
            from utils     import num_to_char
            self.lipnet_model = load_model()
            self.num_to_char  = num_to_char
            print("[VERA] LipNet checkpoint loaded.")
        except Exception as exc:
            print(f"[VERA] LipNet skipped: {exc}")

    # ── Frame processing ─────────────────────────────────────────────────────
    def process_frame(self, frame: np.ndarray, has_audio: bool = False) -> dict:
        self._frame_count += 1
        t0 = time.time()

        emotion_data  = self.emotion.analyze(frame)
        behavior_data = self.behavior.analyze(frame)

        lip_gray, lip_pts = self.lip_ext.extract(frame)
        lip_mov            = self.lip_ext.get_lip_movement_score(frame)
        mouth_open, _      = self.lip_ext.is_mouth_open(frame)

        if lip_gray is not None:
            self._lip_buf.append(lip_gray)

        # Run LipNet every 75 frames
        if (self.lipnet_model is not None
                and len(self._lip_buf) == self.LIPNET_FRAMES
                and self._frame_count % self.LIPNET_FRAMES == 0):
            self._latest_lip_text = self._run_lipnet()

        sync = self._latest_sync if self._latest_sync else {
            "score": 1.0, "risk": 0.0, "is_synced": True,
            "verdict": "No audio", "lip_text": "", "audio_text": "",
        }

        deception_data = self.deception.calculate(
            emotion_data, behavior_data, sync, lip_mov, has_audio
        )

        # Draw overlays
        annotated = frame.copy()
        annotated = self.behavior.draw_overlays(annotated, behavior_data)
        annotated = self._draw_emotion_overlay(annotated, emotion_data)
        annotated = self._draw_risk_bar(annotated, deception_data["score"])
        if lip_pts is not None:
            for pt in lip_pts:
                cv2.circle(annotated, tuple(pt), 1, (0, 200, 255), -1)

        self._check_alerts(deception_data, behavior_data, emotion_data)
        ms = round((time.time() - t0) * 1000, 1)

        return {
            "frame_id":       self._frame_count,
            "processing_ms":  ms,
            "emotion":        emotion_data,
            "behavior":       behavior_data,
            "lip_text":       self._latest_lip_text,
            "audio_text":     self._latest_audio,
            "sync":           sync,
            "deception":      deception_data,
            "lip_movement":   lip_mov,
            "mouth_open":     mouth_open,
            "annotated_frame":annotated,
            "alerts":         list(self._alerts[-5:]),
        }

    def set_audio_text(self, audio_text: str):
        """Update the current audio transcription and recompute sync."""
        self._latest_audio = audio_text
        self._latest_sync  = self.audio.compute_sync_score(
            self._latest_lip_text, audio_text
        )

    # ── LipNet inference ─────────────────────────────────────────────────────
    def _run_lipnet(self) -> str:
        try:
            import tensorflow as tf
            arr  = np.array(list(self._lip_buf), dtype=np.float32)
            arr  = (arr - arr.mean()) / (arr.std() + 1e-6)
            arr  = arr[..., np.newaxis]            # (75, 46, 140, 1)
            t    = tf.expand_dims(arr, 0)          # (1, 75, 46, 140, 1)
            yhat = self.lipnet_model.predict(t, verbose=0)
            try:
                import tf_keras as keras
            except ImportError:
                import tensorflow.keras as keras
            dec  = keras.backend.ctc_decode(
                yhat, input_length=[self.LIPNET_FRAMES], greedy=True
            )[0][0].numpy()
            text = tf.strings.reduce_join(
                self.num_to_char(dec)
            ).numpy().decode("utf-8").strip()
            return text
        except Exception as exc:
            return f"[LipNet error: {exc}]"

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

        if deception["score"] >= 60 and not _recent("High risk"):
            self._alerts.append({"time": ts, "msg": f"High risk score: {deception['score']:.0f}%"})

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

        # Transcribe audio first
        audio_text = ""
        try:
            ar = self.audio.transcribe_file(video_path)
            audio_text = ar.get("text", "")
            if audio_text:
                self.set_audio_text(audio_text)
        except Exception:
            pass

        frame_results, idx = [], 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            idx += 1
            if idx % 3 != 0:           # analyse every 3rd frame for speed
                continue
            r = self.process_frame(frame, has_audio=bool(audio_text))
            frame_results.append({
                "frame_id":  r["frame_id"],
                "emotion":   r["emotion"].get("dominant"),
                "deception": r["deception"]["score"],
                "gaze":      r["behavior"]["gaze"]["direction"],
                "blink":     r["behavior"]["blink"]["rate"],
                "head":      r["behavior"]["head_pose"]["direction"],
                "lip_text":  r["lip_text"],
            })
            if writer:
                writer.write(r["annotated_frame"])

        cap.release()
        if writer:
            writer.release()

        summary = self.deception.get_session_summary()
        summary.update({
            "audio_transcription": audio_text,
            "total_frames":        idx,
            "analyzed_frames":     len(frame_results),
            "alerts":              self._alerts,
            "video_path":          video_path,
        })
        return {"summary": summary, "frames": frame_results}
'''

# ─────────────────────────────────────────────────────────────────────────────
FILES = {
    "vera/behavioral_analyzer.py": BEHAVIORAL,
    "vera/audio_analyzer.py":      AUDIO,
    "vera/deception_scorer.py":    DECEPTION,
    "vera/vera_pipeline.py":       PIPELINE,
}

for rel_path, content in FILES.items():
    full_path = os.path.join(BASE, rel_path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as fh:
        fh.write(content)
    lines = content.count("\n")
    print(f"  wrote  {rel_path}  ({lines} lines)")

print("\nAll VERA v2 modules written successfully.")

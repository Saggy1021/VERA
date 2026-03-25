"""
VERA - Behavioral Analyzer (Production v2)
MediaPipe 0.10+ FaceLandmarker Tasks API (478 landmarks) — no training needed.
Outputs: Eye gaze direction, blink rate (EAR), head pose (solvePnP),
         eye contact, all with temporal smoothing.
"""
import cv2
import numpy as np
import os, sys
import time
from collections import deque, Counter

# Shared MediaPipe 0.10+ Tasks API wrapper (replaces removed mp.solutions)
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)
import face_landmark as _fl

# ── Landmark indices --------------------------------------------------------
L_EYE_TOP, L_EYE_BOT = 159, 145
L_EYE_OUT, L_EYE_INN = 33,  133
R_EYE_TOP, R_EYE_BOT = 386, 374
R_EYE_OUT, R_EYE_INN = 362, 263
L_IRIS, R_IRIS        = 468, 473
NOSE_TIP, CHIN        = 4,   152
L_MOUTH, R_MOUTH      = 61,  291
# Second vertical eye landmark pairs for 2-pair EAR (Soukupova et al.)
L_EYE_TOP2, L_EYE_BOT2 = 160, 144   # second pair, left eye
R_EYE_TOP2, R_EYE_BOT2 = 385, 373   # second pair, right eye

# 0.25 is the literature standard; 0.21 under-counts blinks by missing
# shallow closures that are genuine blinks.
BLINK_EAR_THRESH = 0.25
BLINK_CONSEC     = 2
BLINK_WIN_SEC    = 60
GAZE_SMOOTH_N    = 12

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
        self._blink_count    = 0
        self._eye_closed_frm = 0
        self._blink_times    = deque()
        self._gaze_hist      = deque(maxlen=GAZE_SMOOTH_N)
        self._yaw_hist       = deque(maxlen=20)
        self._last_result    = None
        # Adaptive blink baseline: tracks open-eye EAR values
        self._ear_baseline   = deque(maxlen=60)
        # Rolling metric windows for deception_scorer v3
        self._gaze_avoid_hist = deque(maxlen=30)   # gaze_avoidance_rate
        self._ear_hist        = deque(maxlen=20)   # ear_variance
        self._head_dev_hist   = deque(maxlen=30)   # head_deviation_mean
        self._ec_hist         = deque(maxlen=20)   # eye_contact_rate
        
        # Exam Invigilation Additions
        self._illum_hist      = deque(maxlen=30)
        self._saccade_hist    = deque(maxlen=15)
        self._last_gaze_vec   = None
        
        # 5-Second Persistence Trackers (to stop flickering)
        self._5sec_trackers = {
            "illumination": 0.0,
            "saccade": 0.0,
            "gaze_avoid": 0.0
        }
        
        # Personal Baseline Calibration
        self._frame_count = 0
        self._calibration_frames = 100
        self._baselines = {
            "ear": 0.0,
            "yaw": 0.0,
            "pitch": 0.0,
            "calibrated": False
        }

    # ── Public API ─────────────────────────────────────────────────────────
    def analyze(self, frame: np.ndarray) -> dict:
        # detect_bgr caches by BGR frame id — the same frame object shared with
        # LipExtractor means MediaPipe runs exactly once per pipeline frame.
        result = _fl.detect_bgr(frame)
        if not result.face_landmarks:
            return self._empty()

        lm = result.face_landmarks[0]   # list of NormalizedLandmark .x/.y/.z
        h, w = frame.shape[:2]

        face_count = len(result.face_landmarks)
        head      = self._compute_head_pose(lm, w, h)
        gaze      = self._compute_gaze(lm, w, h, head["yaw"], head["pitch"])
        blink     = self._compute_blink(lm, w, h)
        eye_cont  = self._compute_eye_contact(lm, w, h)

        # Temporal smoothing on gaze
        self._gaze_hist.append(gaze["direction"])
        smooth_gaze = Counter(self._gaze_hist).most_common(1)[0][0]
        gaze["direction"] = smooth_gaze

        # Rolling head yaw
        self._yaw_hist.append(abs(head["yaw"]))
        avg_yaw = float(np.mean(self._yaw_hist))

        blink_risk = min(max(blink["rate"] - 20, 0) / 30, 1.0) * 0.55 if blink["rate"] > 20 else 0.0
        gaze_risk  = GAZE_MEANING.get(smooth_gaze, GAZE_MEANING["center"])["risk"]
        
        # ── Dynamic Baseline Calibration ──────────────────────────────
        self._frame_count += 1
        if self._frame_count < self._calibration_frames:
            self._baselines["ear"] += blink["ear"]
            self._baselines["yaw"] += head["yaw"]
            self._baselines["pitch"] += head["pitch"]
            head_risk = 0.0
            dev_yaw = abs(head["yaw"])
            dev_pitch = abs(head["pitch"])
        else:
            if not self._baselines["calibrated"]:
                self._baselines["ear"] /= self._calibration_frames
                self._baselines["yaw"] /= self._calibration_frames
                self._baselines["pitch"] /= self._calibration_frames
                self._baselines["calibrated"] = True
            
            # Calculate deviations from strict personal baseline, not perfect true center
            dev_yaw = abs(head["yaw"] - self._baselines["yaw"])
            dev_pitch = abs(head["pitch"] - self._baselines["pitch"])
            head_risk = min(dev_yaw / 45.0, 1.0) * 0.35

        # ── Rolling metrics for deception_scorer v3 ──────────────────────────
        # Avoidance = any gaze direction other than center
        self._gaze_avoid_hist.append(0 if smooth_gaze == "center" else 1)
        self._ear_hist.append(blink["ear"] - (self._baselines["ear"] if self._baselines["calibrated"] else 0))
        peak_dev = max(dev_yaw, dev_pitch)
        self._head_dev_hist.append(peak_dev)
        self._ec_hist.append(1 if eye_cont["making_contact"] else 0)

        gaze_avoidance_rate = float(np.mean(self._gaze_avoid_hist)) if self._gaze_avoid_hist else 0.0
        ear_var = float(np.var(list(self._ear_hist))) if len(self._ear_hist) >= 2 else 0.0
        head_deviation_mean = float(np.mean(self._head_dev_hist)) if self._head_dev_hist else 0.0
        eye_contact_rate    = float(np.mean(self._ec_hist))        if self._ec_hist        else 1.0
        # Store ear_variance inside blink dict for deception_scorer
        blink["ear_variance"] = round(ear_var, 5)

        # ── Exam Proctoring Anomalies (Illumination & Saccades) ──────────
        ts_now = time.time()
        
        # Illumination Tracking (Screen flashes via EMA difference)
        xs = [min(max(l.x * w, 0), w) for l in lm]
        ys = [min(max(l.y * h, 0), h) for l in lm]
        x_min, x_max = int(min(xs)), int(max(xs))
        y_min, y_max = int(min(ys)), int(max(ys))
        illum_diff = 0.0
        if x_min < x_max and y_min < y_max:
            gray_crop = cv2.cvtColor(frame[y_min:y_max, x_min:x_max], cv2.COLOR_BGR2GRAY)
            cur_bright = np.mean(gray_crop)
            if len(self._illum_hist) == 30:
                # Compare current to the baseline from 30 frames (~3 sec) ago
                baseline = self._illum_hist[0]
                illum_diff = abs(cur_bright - baseline)
            self._illum_hist.append(cur_bright)
            
        if illum_diff > 25.0: # Huge unnatural brightness change
            if self._5sec_trackers["illumination"] == 0.0:
                self._5sec_trackers["illumination"] = ts_now
        else:
            self._5sec_trackers["illumination"] = 0.0

        # Rapid Saccade Tracking (Lap-glancing)
        current_gaze_vec = np.array([gaze["h_ratio"], gaze["v_ratio"]])
        if self._last_gaze_vec is not None:
            saccade_speed = float(np.linalg.norm(current_gaze_vec - self._last_gaze_vec))
            self._saccade_hist.append(saccade_speed)
        self._last_gaze_vec = current_gaze_vec
        
        rapid_saccade_rate = sum(1 for s in self._saccade_hist if s > 0.15) / max(len(self._saccade_hist), 1)
        if rapid_saccade_rate > 0.35:
            if self._5sec_trackers["saccade"] == 0.0:
                self._5sec_trackers["saccade"] = ts_now
        else:
            self._5sec_trackers["saccade"] = 0.0
            
        # Gaze Avoidance Persistence
        if smooth_gaze != "center":
            if self._5sec_trackers["gaze_avoid"] == 0.0:
                self._5sec_trackers["gaze_avoid"] = ts_now
        else:
            self._5sec_trackers["gaze_avoid"] = 0.0

        result = {
            "gaze":                gaze,
            "blink":               blink,
            "head_pose":           head,
            "eye_contact":         eye_cont,
            "gaze_interpretation": GAZE_MEANING.get(smooth_gaze, GAZE_MEANING["center"]),
            "blink_risk":          round(blink_risk, 3),
            "gaze_risk":           round(gaze_risk,  3),
            "head_risk":           round(head_risk,  3),
            "gaze_avoidance_rate": round(gaze_avoidance_rate, 3),
            "ear_variance":        round(ear_var, 5),
            "head_deviation_mean": round(head_deviation_mean, 1),
            "eye_contact_rate":    round(eye_contact_rate, 3),
            "illumination_diff":   round(illum_diff, 2),
            "rapid_saccade_rate":  round(rapid_saccade_rate, 3),
            "persistence": {
                "illumination": (ts_now - self._5sec_trackers["illumination"]) if self._5sec_trackers["illumination"] > 0 else 0.0,
                "saccade":      (ts_now - self._5sec_trackers["saccade"])      if self._5sec_trackers["saccade"] > 0      else 0.0,
                "gaze_avoid":   (ts_now - self._5sec_trackers["gaze_avoid"])   if self._5sec_trackers["gaze_avoid"] > 0   else 0.0,
            },
            "face_count":          face_count,
            "face_detected":       True,
            "landmarks":           lm,
            "frame_shape":         frame.shape,
        }
        self._last_result = result
        return result

    def draw_overlays(self, frame: np.ndarray, data: dict) -> np.ndarray:
        if data.get("landmarks") is None:
            return frame
        lm   = data["landmarks"]   # list of NormalizedLandmark (.x/.y/.z)
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

    def _compute_gaze(self, lm, w, h, head_yaw: float = 0.0, head_pitch: float = 0.0):
        has_iris = len(lm) > 473
        
        # Helper: get 3D coordinates directly
        def pt3d(idx):
            return np.array([lm[idx].x, lm[idx].y, lm[idx].z])

        li = pt3d(L_IRIS) if has_iris else (pt3d(L_EYE_OUT) + pt3d(L_EYE_INN)) / 2
        ri = pt3d(R_IRIS) if has_iris else (pt3d(R_EYE_OUT) + pt3d(R_EYE_INN)) / 2

        # 3D Eye Centers
        lc = (pt3d(L_EYE_OUT) + pt3d(L_EYE_INN)) / 2
        rc = (pt3d(R_EYE_OUT) + pt3d(R_EYE_INN)) / 2
        
        # 3D Eye Widths / Heights (for stable normalization)
        lw = np.linalg.norm(pt3d(L_EYE_OUT) - pt3d(L_EYE_INN))
        rw = np.linalg.norm(pt3d(R_EYE_OUT) - pt3d(R_EYE_INN))
        lh = np.linalg.norm(pt3d(L_EYE_TOP) - pt3d(L_EYE_BOT))
        rh = np.linalg.norm(pt3d(R_EYE_TOP) - pt3d(R_EYE_BOT))

        # Raw Iris Displacement Ratio (-0.5 to 0.5)
        # We look at the X and Y distance from the iris to the eye center 
        # relative to the total width/height of the eye socket.
        lx_disp = (li[0] - lc[0]) / max(lw, 1e-6)
        rx_disp = (ri[0] - rc[0]) / max(rw, 1e-6)
        ly_disp = (li[1] - lc[1]) / max(lh, 1e-6)
        ry_disp = (ri[1] - rc[1]) / max(rh, 1e-6)

        avg_x_disp = (lx_disp + rx_disp) / 2.0
        avg_y_disp = (ly_disp + ry_disp) / 2.0

        # MAGIC: 3D Head Pose Compensation!
        # A turned head naturally shifts the eye socket relative to the camera.
        # We subtract the head rotation (scaled radially) to find where the 
        # eyeballs are pointing *relative to the face*.
        comp_x = avg_x_disp - (head_yaw / 90.0) * 0.45
        comp_y = avg_y_disp - (head_pitch / 90.0) * 0.45

        # Normalize back to traditional 0-1 scale (0.5 is center)
        h_val = comp_x + 0.5
        v_val = comp_y + 0.5

        # Tuned bounds: highly sensitive gaze (±0.05 from center) to catch extreme eyeballs
        hd = "right"  if h_val > 0.55 else ("left"  if h_val < 0.45 else "center")
        vd = "upper"  if v_val < 0.42 else ("lower" if v_val > 0.58 else "center")

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

    def _ear(self, lm, top, bot, top2, bot2, out, inn, w, h):
        """2-pair Eye Aspect Ratio (Soukupova et al.) for robustness
        against head roll and single-landmark jitter."""
        px = lambda i: self._px(lm, i, w, h)
        vert1 = np.linalg.norm(px(top)  - px(bot))
        vert2 = np.linalg.norm(px(top2) - px(bot2))
        horiz = np.linalg.norm(px(out)  - px(inn))
        return (vert1 + vert2) / max(2.0 * horiz, 1e-6)

    def _compute_blink(self, lm, w, h):
        le = self._ear(lm, L_EYE_TOP, L_EYE_BOT, L_EYE_TOP2, L_EYE_BOT2, L_EYE_OUT, L_EYE_INN, w, h)
        re = self._ear(lm, R_EYE_TOP, R_EYE_BOT, R_EYE_TOP2, R_EYE_BOT2, R_EYE_OUT, R_EYE_INN, w, h)
        avg = (le + re) / 2.0

        # Adaptive threshold: use 75% of rolling open-eye EAR baseline
        # This adapts to different lighting conditions and face shapes
        if len(self._ear_baseline) >= 5:
            adaptive_thresh = float(np.median(self._ear_baseline)) * 0.75
        else:
            adaptive_thresh = BLINK_EAR_THRESH
        # Clamp to reasonable bounds
        adaptive_thresh = max(0.18, min(adaptive_thresh, 0.30))

        closed = avg < adaptive_thresh
        now = time.time()

        if closed:
            self._eye_closed_frm += 1
        else:
            # Track open-eye EAR for baseline (only when NOT blinking)
            if self._eye_closed_frm < BLINK_CONSEC:
                self._ear_baseline.append(avg)
            if self._eye_closed_frm >= BLINK_CONSEC:
                self._blink_count += 1
                self._blink_times.append(now)
            self._eye_closed_frm = 0

        while self._blink_times and now - self._blink_times[0] > BLINK_WIN_SEC:
            self._blink_times.popleft()

        n = len(self._blink_times)
        elapsed = min(now - self._blink_times[0], BLINK_WIN_SEC) if n > 0 else BLINK_WIN_SEC
        rate = (n / max(elapsed, 1)) * 60
        return {
            "total":    int(self._blink_count),
            "rate":     round(float(rate), 1),
            "ear":      round(float(avg), 3),
            "closed":   bool(closed),
            "elevated": bool(rate > 25),
        }

    def _compute_head_pose(self, lm, w, h):
        import math
        # Direct Trigonometry using MediaPipe 3D Z-depth coordinates
        # MediaPipe provides natively aligned Z coordinates relative to the face center.
        # This completely avoids the instability of OpenCV's PnP solver for face meshes.

        out_l = np.array([lm[L_EYE_OUT].x, lm[L_EYE_OUT].y, lm[L_EYE_OUT].z])
        out_r = np.array([lm[R_EYE_OUT].x, lm[R_EYE_OUT].y, lm[R_EYE_OUT].z])
        nose  = np.array([lm[NOSE_TIP].x,  lm[NOSE_TIP].y,  lm[NOSE_TIP].z])
        chin  = np.array([lm[CHIN].x,      lm[CHIN].y,      lm[CHIN].z])

        # Yaw: angle between the two outer eye corners in the XZ plane
        yaw_rad = math.atan2(out_l[2] - out_r[2], out_l[0] - out_r[0])
        yaw     = math.degrees(yaw_rad)

        # Pitch: angle between nose tip and chin in the YZ plane
        pitch_rad = math.atan2(chin[2] - nose[2], chin[1] - nose[1])
        # Offset typical resting face pitch to 0
        pitch = math.degrees(pitch_rad) + 15.0 

        # Roll: angle between the two outer eye corners in the XY plane
        roll_rad = math.atan2(out_l[1] - out_r[1], out_l[0] - out_r[0])
        roll     = math.degrees(roll_rad)

        direction = "Forward"
        if   yaw   >  15: direction = "Right"
        elif yaw   < -15: direction = "Left"
        elif pitch < -15: direction = "Down"
        elif pitch >  15: direction = "Up"

        return {
            "yaw":       round(yaw,   1),
            "pitch":     round(pitch, 1),
            "roll":      round(roll,  1),
            "direction": direction,
            "is_turned": abs(yaw) > 15 or abs(pitch) > 15,
        }

    def _compute_eye_contact(self, lm, w, h):
        """Iris-based eye contact detection.
        Measures how far each iris is from the center of its eye socket.
        Works correctly regardless of head rotation."""
        has_iris = len(lm) > 473
        if not has_iris:
            # Fallback: simple nose-vs-eye check
            nx  = lm[NOSE_TIP].x
            emx = (lm[L_EYE_OUT].x + lm[R_EYE_OUT].x) / 2
            diff = abs(nx - emx)
            return {"making_contact": diff < 0.05, "diff": round(diff, 4)}

        px = lambda i: self._px(lm, i, w, h)
        # Iris positions
        li = px(L_IRIS)
        ri = px(R_IRIS)
        # Eye socket centers
        l_center = (px(L_EYE_OUT) + px(L_EYE_INN)) / 2
        r_center = (px(R_EYE_OUT) + px(R_EYE_INN)) / 2
        # Eye socket widths (for normalization)
        l_width = max(np.linalg.norm(px(L_EYE_OUT) - px(L_EYE_INN)), 1.0)
        r_width = max(np.linalg.norm(px(R_EYE_OUT) - px(R_EYE_INN)), 1.0)
        # Normalized displacement: 0 = iris at center, 1 = iris at edge
        l_disp = np.linalg.norm(li - l_center) / (l_width * 0.5)
        r_disp = np.linalg.norm(ri - r_center) / (r_width * 0.5)
        avg_disp = float((l_disp + r_disp) / 2.0)
        return {"making_contact": avg_disp < 0.35, "diff": round(avg_disp, 4)}

    def _empty(self):
        return {
            "gaze":                {"direction": "unknown", "h_ratio": 0.5, "v_ratio": 0.5},
            "blink":               {"total": 0, "rate": 0, "ear": 0, "closed": False, "elevated": False, "ear_variance": 0.0},
            "head_pose":           {"yaw": 0, "pitch": 0, "roll": 0, "direction": "Unknown", "is_turned": False},
            "eye_contact":         {"making_contact": False, "diff": 0},
            "gaze_interpretation": GAZE_MEANING["center"],
            "blink_risk":          0.0,
            "gaze_risk":           0.0,
            "head_risk":           0.0,
            "gaze_avoidance_rate": 0.0,
            "ear_variance":        0.0,
            "head_deviation_mean": 0.0,
            "eye_contact_rate":    1.0,
            "face_count":          0,
            "face_detected":       False,
            "landmarks":           None,
            "frame_shape":         (480, 640, 3),
        }

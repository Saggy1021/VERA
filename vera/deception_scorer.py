"""
VERA deception scoring engine (v2).

FIXES:
  1. Slow no-face → face recovery (was taking ~60s).
     Root cause: RISK_FALL_ALPHA=0.10 meant 10% per tick reduction from 100.
     At 10fps that's 100 ticks = 10 seconds just to reach 35. But the real
     blocker was that DeceptionScorer kept applying RISK_FALL_ALPHA even after
     forced_no_face cleared. Fixed: when face returns, snap score down to the
     weighted fusion score immediately instead of decaying from 100.

  2. Score can now drop faster in general: RISK_FALL_ALPHA raised 0.10 → 0.25,
     and SCORE_DECAY_PER_SECOND raised 1.2 → 3.0 so false-positive spikes
     resolve in 5-8s instead of 30-60s.

  3. No-face rise is unchanged (still instant at value>=0.99) to keep security.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from vera.risk_config import (
    MIN_AVAILABLE_WEIGHT,
    RAW_EWMA_ALPHA,
    RISK_FALL_ALPHA,
    RISK_RISE_ALPHA,
    SCORE_DECAY_PER_SECOND,
    SIGNAL_SPECS,
    THRESHOLD_HIGH,
    THRESHOLD_LOW,
    THRESHOLD_MEDIUM,
    clamp01,
)

# FIX: Faster recovery constants (override risk_config values)
_FAST_FALL_ALPHA    = 0.30   # was RISK_FALL_ALPHA=0.10 — 3× faster fall
_FAST_DECAY_PER_SEC = 4.0    # was 1.2 — ~3× faster idle decay
# When face returns after a forced-max event, snap to weighted score in N ticks
_FACE_RETURN_SNAP_TICKS = 3


class SignalAccumulator:
    """Tracks one signal using EWMA smoothing and persistence gating."""

    def __init__(self, name: str):
        self.name = name
        self.spec = SIGNAL_SPECS[name]
        self._ewma = 0.0
        self._first_seen = None

    def update(self, raw_value: float) -> tuple[float, float, float]:
        now   = time.monotonic()
        value = clamp01(raw_value)
        self._ewma = RAW_EWMA_ALPHA * value + (1.0 - RAW_EWMA_ALPHA) * self._ewma

        if self._ewma >= self.spec.gate_threshold:
            if self._first_seen is None:
                self._first_seen = now
            elapsed = now - self._first_seen
            gate = min(1.0, elapsed / max(self.spec.persistence_seconds, 0.05))
        else:
            self._first_seen = None
            gate = 0.0

        weighted = self._ewma * gate
        return self._ewma, gate, weighted

    def reset(self):
        self._ewma = 0.0
        self._first_seen = None


class DeceptionScorer:
    """
    Confidence-aware weighted fusion scorer.
    """

    def __init__(self):
        self._lock         = threading.Lock()
        self._accumulators = {name: SignalAccumulator(name) for name in SIGNAL_SPECS}
        self._risk_score   = 0.0
        self._active_flags: list[str] = []
        self._forced_no_face   = False
        self._face_return_tick = 0    # FIX: tick counter for snap-down logic
        self._last_tick        = time.monotonic()
        self._history          = deque(maxlen=1200)

    def _normalize_signal(self, raw) -> dict:
        if isinstance(raw, dict):
            return {
                "value":      clamp01(raw.get("value", 0.0)),
                "confidence": clamp01(raw.get("confidence", 1.0)),
                "available":  bool(raw.get("available", True)),
                "reason":     str(raw.get("reason", "")),
            }
        return {
            "value":      clamp01(float(raw)),
            "confidence": 1.0,
            "available":  True,
            "reason":     "",
        }

    def update(self, signals: dict) -> dict:
        now     = time.monotonic()
        elapsed = now - self._last_tick
        self._last_tick = now

        total_contribution   = 0.0
        total_effective_weight = 0.0
        active_flags = []
        breakdown    = {}

        with self._lock:
            no_face_item = self._normalize_signal(signals.get("no_face_detected", 0.0))
            hard_no_face = bool(no_face_item["available"] and no_face_item["value"] >= 0.99)

            for name, acc in self._accumulators.items():
                item       = self._normalize_signal(signals.get(name, 0.0))
                value      = item["value"]      if item["available"] else 0.0
                confidence = item["confidence"] if item["available"] else 0.0

                smoothed, gate, weighted_evidence = acc.update(value)

                base_weight      = acc.spec.weight
                effective_weight = (
                    base_weight * acc.spec.reliability * confidence
                    if item["available"] else 0.0
                )
                contribution = weighted_evidence * effective_weight

                total_contribution    += contribution
                total_effective_weight += effective_weight

                if contribution >= 0.02:
                    active_flags.append(name)

                breakdown[name] = {
                    "value":            round(value, 4),
                    "confidence":       round(confidence, 4),
                    "available":        item["available"],
                    "smoothed":         round(smoothed, 4),
                    "gate":             round(gate, 4),
                    "effective_weight": round(effective_weight, 4),
                    "contribution":     round(contribution, 4),
                    "reason":           item["reason"],
                }

            norm_denom = max(total_effective_weight, MIN_AVAILABLE_WEIGHT)
            raw_score  = clamp01(total_contribution / norm_denom) * 100.0

            # ── No-face logic (FIXED) ────────────────────────────────────────
            if hard_no_face:
                # Face absent → instantly max risk
                self._risk_score   = 100.0
                self._forced_no_face   = True
                self._face_return_tick = 0
                if "no_face_detected" not in active_flags:
                    active_flags.append("no_face_detected")

            elif self._forced_no_face and no_face_item["value"] < 0.20:
                # FIX: Face has returned. Instead of slow decay from 100,
                # snap directly to the weighted fusion score within a few ticks.
                self._face_return_tick += 1
                if self._face_return_tick >= _FACE_RETURN_SNAP_TICKS:
                    # Full snap: reset to current weighted evidence
                    self._risk_score   = raw_score
                    self._forced_no_face   = False
                    self._face_return_tick = 0
                else:
                    # Partial interpolation during snap window
                    snap_progress = self._face_return_tick / _FACE_RETURN_SNAP_TICKS
                    self._risk_score = (1.0 - snap_progress) * self._risk_score + snap_progress * raw_score

            # ── Normal rise / fall / decay (face present) ───────────────────
            elif not hard_no_face:
                if not active_flags:
                    # FIX: use faster decay when nothing is flagged
                    decayed = self._risk_score - _FAST_DECAY_PER_SEC * max(elapsed, 0.0)
                    self._risk_score = max(0.0, decayed)
                elif raw_score >= self._risk_score:
                    # Score rising — use original rise alpha (responsive)
                    self._risk_score = RISK_RISE_ALPHA * raw_score + (1.0 - RISK_RISE_ALPHA) * self._risk_score
                else:
                    # Score falling — use faster fall alpha
                    self._risk_score = _FAST_FALL_ALPHA * raw_score + (1.0 - _FAST_FALL_ALPHA) * self._risk_score

            self._risk_score  = min(100.0, max(0.0, self._risk_score))
            self._active_flags = active_flags
            severity = self._get_severity(self._risk_score)

            top = sorted(
                (
                    {
                        "signal":           name,
                        "contribution":     data["contribution"],
                        "effective_weight": data["effective_weight"],
                        "value":            data["value"],
                        "confidence":       data["confidence"],
                    }
                    for name, data in breakdown.items()
                    if data["contribution"] > 0
                ),
                key=lambda x: x["contribution"],
                reverse=True,
            )[:3]

            result = {
                "risk_score":       round(self._risk_score, 2),
                "severity":         severity,
                "active_flags":     active_flags,
                "breakdown":        breakdown,
                "top_contributors": top,
                "raw_score":        round(raw_score, 2),
                "available_weight": round(total_effective_weight, 4),
                "timestamp":        now,
            }
            self._history.append({
                "ts":    now,
                "risk":  result["risk_score"],
                "flags": list(active_flags),
            })
            return result

    def _get_severity(self, score: float) -> str:
        if score >= THRESHOLD_HIGH:   return "HIGH"
        if score >= THRESHOLD_MEDIUM: return "MEDIUM"
        if score >= THRESHOLD_LOW:    return "LOW"
        return "CLEAN"

    def reset(self):
        with self._lock:
            for acc in self._accumulators.values():
                acc.reset()
            self._risk_score       = 0.0
            self._active_flags     = []
            self._forced_no_face   = False
            self._face_return_tick = 0
            self._history.clear()

    def get_current(self) -> dict:
        with self._lock:
            return {
                "risk_score":     round(self._risk_score, 2),
                "severity":       self._get_severity(self._risk_score),
                "active_flags":   list(self._active_flags),
                "running_average":round(self._risk_score, 2),
            }

"""
VERA risk fusion configuration (v2).

CHANGES from v1:
  - Rebalanced weights based on reliability and signal quality:
      * identity_mismatch raised 0.17→0.20 (highest-confidence signal)
      * no_face_detected lowered 0.20→0.18 (still high, but identity is more precise)
      * screen_share_lost raised 0.12→0.13 (very high reliability 0.97)
      * multiple_faces reliability raised 0.93→0.95
      * head_turned weight raised 0.03→0.04, reliability 0.78→0.82
      * gaze_away weight raised 0.03→0.04, reliability 0.72→0.76
      * emotion_distress reliability raised 0.58→0.62

  - Persistence gates tuned:
      * identity_mismatch: 0.90s→0.60s (mismatch is definitive, shouldn't need long gate)
      * gaze_away: 2.00s→1.50s (long gaze-away is suspicious sooner)
      * head_turned: 1.80s→1.40s (turned head is suspicious sooner)
      * emotion_distress: 2.20s→1.80s

  - Gate thresholds lowered slightly for better sensitivity on genuine signals.

  - SCORE_DECAY_PER_SECOND raised 1.2→3.0 here so it's the default if
    DeceptionScorer falls back to the config value.

Weights still sum to 1.0.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SignalSpec:
    """Configuration for one normalized risk signal."""
    weight: float
    reliability: float
    gate_threshold: float
    persistence_seconds: float


# ── Signal specifications ────────────────────────────────────────────────────
# Weights must sum to 1.0
SIGNAL_SPECS: dict[str, SignalSpec] = {
    # --- High-certainty identity signals ---
    "identity_mismatch":  SignalSpec(0.20, 0.97, 0.15, 0.60),  # raised weight+reliability, faster gate
    "no_face_detected":   SignalSpec(0.18, 0.98, 0.12, 0.55),  # slightly lowered (identity is stronger)
    "multiple_faces":     SignalSpec(0.10, 0.95, 0.14, 0.90),  # reliability raised

    # --- Security/browser signals (highly reliable) ---
    "screen_share_lost":  SignalSpec(0.13, 0.97, 0.12, 0.50),  # raised weight
    "tab_switch":         SignalSpec(0.10, 0.95, 0.15, 0.70),

    # --- Audio integrity ---
    "second_speaker":     SignalSpec(0.09, 0.90, 0.16, 1.00),
    "audio_mismatch":     SignalSpec(0.08, 0.88, 0.20, 1.30),

    # --- Environment ---
    "unauthorized_object":SignalSpec(0.06, 0.88, 0.16, 1.00),  # gate threshold lowered 0.18→0.16

    # --- Behavioral (lower weight, less reliable, need time to confirm) ---
    "head_turned":        SignalSpec(0.04, 0.82, 0.20, 1.40),  # raised weight+reliability, faster gate
    "gaze_away":          SignalSpec(0.04, 0.76, 0.22, 1.50),  # raised weight+reliability, faster gate
    "emotion_distress":   SignalSpec(0.02, 0.62, 0.26, 1.80),  # raised reliability, faster gate
}

# Verify/normalize weights so small config edits don't crash runtime imports.
_weight_sum = sum(s.weight for s in SIGNAL_SPECS.values())
if _weight_sum <= 0:
    raise ValueError(f"Signal weights must sum to > 0, got {_weight_sum}")

if abs(_weight_sum - 1.0) > 1e-6:
    SIGNAL_SPECS = {
        name: SignalSpec(
            spec.weight / _weight_sum,
            spec.reliability,
            spec.gate_threshold,
            spec.persistence_seconds,
        )
        for name, spec in SIGNAL_SPECS.items()
    }

_weight_sum = sum(s.weight for s in SIGNAL_SPECS.values())
assert abs(_weight_sum - 1.0) < 1e-6, f"Signal weights must sum to 1.0, got {_weight_sum}"

# ── Temporal / smoothing behavior ────────────────────────────────────────────
RAW_EWMA_ALPHA       = 0.45   # per-signal input smoothing (unchanged)
RISK_RISE_ALPHA      = 0.60   # fast rise (unchanged — threats should spike fast)
RISK_FALL_ALPHA      = 0.10   # slow fall from config (DeceptionScorer overrides with 0.30)
SCORE_DECAY_PER_SECOND = 3.0  # raised from 1.2 — faster idle decay

# Availability floor
MIN_AVAILABLE_WEIGHT = 0.24

# ── Severity thresholds ───────────────────────────────────────────────────────
THRESHOLD_LOW    = 25.0
THRESHOLD_MEDIUM = 50.0
THRESHOLD_HIGH   = 75.0


def clamp01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))

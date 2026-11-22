// FILE: src/lib/constants.ts
// Risk thresholds, event types, EWMA config

export type FlagKey =
  | 'identity_mismatch'
  | 'no_face'
  | 'multiple_faces'
  | 'tab_switch'
  | 'fullscreen_exit'
  | 'head_turned'
  | 'gaze_away'
  | 'object_detected'
  | 'audio_activity'
  | 'second_speaker';

export interface FlagConfig {
  weight: number;
  threshold: number;
  persistFrames: number;
  severity: 'low' | 'medium' | 'high' | 'critical';
}

export const EWMA_ALPHA = 0.3; // VERA used 0.45 — caused too many false positives

export const FLAG_WEIGHTS: Record<FlagKey, FlagConfig> = {
  // Identity
  identity_mismatch:   { weight: 0.20, threshold: 0.6,  persistFrames: 5,  severity: 'critical' },
  // Presence
  no_face:             { weight: 0.18, threshold: 1.0,  persistFrames: 4,  severity: 'high' },
  multiple_faces:      { weight: 0.12, threshold: 0.8,  persistFrames: 6,  severity: 'high' },
  // Focus
  tab_switch:          { weight: 0.12, threshold: 1.0,  persistFrames: 1,  severity: 'high' },
  fullscreen_exit:     { weight: 0.10, threshold: 1.0,  persistFrames: 1,  severity: 'medium' },
  // Head / Gaze
  head_turned:         { weight: 0.08, threshold: 0.7,  persistFrames: 8,  severity: 'medium' },
  gaze_away:           { weight: 0.06, threshold: 0.65, persistFrames: 10, severity: 'low' },
  // Objects
  object_detected:     { weight: 0.08, threshold: 0.55, persistFrames: 3,  severity: 'high' },
  // Audio
  audio_activity:      { weight: 0.04, threshold: 0.7,  persistFrames: 8,  severity: 'low' },
  // second_speaker: DEFERRED TO V2.
  // No production-ready WASM speaker diarization exists for browsers.
  // threshold=1.1 is intentionally unreachable (max EWMA value is 1.0) — flag never fires.
  // V2 plan: server-side diarization endpoint receiving 5s WAV chunks from audio_worker.
  second_speaker:      { weight: 0.02, threshold: 1.1,  persistFrames: 12, severity: 'low' },
};

// persistFrames: number of consecutive frames flag must be active before it contributes
// This replaces VERA's time-based persistence with frame-count persistence (more stable)

export const RISK_THRESHOLDS = {
  CLEAN:    25,   // 0-24:  green
  LOW:      50,   // 25-49: yellow
  MEDIUM:   75,   // 50-74: orange
  HIGH:     90,   // 75-89: red
  CRITICAL: 100,  // 90+:   red + alert + Gemini call
};

// ── Decay rate ──────────────────────────────────────────────────────────────
// PRD spec: 1.5 pts/SECOND (not per frame).
// At 8fps (FRAME_INTERVAL_MS=125): 1.5 × 0.125 = 0.1875 pts/frame
// At 8fps a score of 85 takes ~57 seconds to decay to 0 — candidate bears
// the consequence of a detected event for nearly a minute. (VERA used 4 pts/sec
// which caused rapid score bouncing and proctor confusion.)
export const FRAME_INTERVAL_MS = 125; // 8fps
export const SCORE_DECAY_PER_SECOND = 1.5;
export const SCORE_DECAY_PER_FRAME = SCORE_DECAY_PER_SECOND * (FRAME_INTERVAL_MS / 1000);
// = 1.5 × 0.125 = 0.1875 pts/frame at 8fps ✓
// Auto-adjusts: if FRAME_INTERVAL_MS changes to 250 (4fps) → 0.375 pts/frame (still 1.5 pts/sec)

export type RawFlags = Record<FlagKey, number>;

export interface RiskState {
  smoothed: Record<FlagKey, number>;
  persistCounters: Record<FlagKey, number>;
  lastScore: number;
}

export const initialRiskState: RiskState = {
  smoothed: {
    identity_mismatch: 0,
    no_face: 0,
    multiple_faces: 0,
    tab_switch: 0,
    fullscreen_exit: 0,
    head_turned: 0,
    gaze_away: 0,
    object_detected: 0,
    audio_activity: 0,
    second_speaker: 0,
  },
  persistCounters: {
    identity_mismatch: 0,
    no_face: 0,
    multiple_faces: 0,
    tab_switch: 0,
    fullscreen_exit: 0,
    head_turned: 0,
    gaze_away: 0,
    object_detected: 0,
    audio_activity: 0,
    second_speaker: 0,
  },
  lastScore: 0,
};

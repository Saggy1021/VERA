// FILE: src/lib/scoring.ts
// Risk scoring engine — runs entirely in the browser

import {
  EWMA_ALPHA,
  FLAG_WEIGHTS,
  FLAG_SCORE_CONTRIBUTION,
  SCORE_DECAY_PER_FRAME,
  type FlagKey,
  type RawFlags,
  type RiskState,
} from './constants';

export function updateRiskEWMA(
  rawFlags: RawFlags,
  state: RiskState
): RiskState {
  const newSmoothed: Record<FlagKey, number> = {} as Record<FlagKey, number>;
  const newPersistCounters = { ...state.persistCounters };

  for (const [key, config] of Object.entries(FLAG_WEIGHTS)) {
    const flagKey = key as FlagKey;
    const raw = rawFlags[flagKey] ?? 0; // 0.0 or 1.0
    // EWMA smooth
    const prev = state.smoothed[flagKey] ?? 0;
    newSmoothed[flagKey] = EWMA_ALPHA * raw + (1 - EWMA_ALPHA) * prev;

    // Persist-frame counter: soft decrement-by-2 (NOT hard-reset).
    //
    // WHY NOT HARD-RESET:
    // MediaPipe at 8fps occasionally drops 1 frame (face mesh not detected for
    // exactly 1 frame on modest hardware). Hard-reset resets a counter of 7 back
    // to 0 on that single missed frame, so flags with persistFrames=8 never fire.
    //
    // WHY DECREMENT-BY-2:
    // A flag clears reliably in roughly persistFrames/2 frames after genuine
    // clearance, but a single dropped frame only costs 2 frames of progress.
    // This tolerates noise spikes while still draining counters quickly enough
    // that genuine clearance is reflected within ~1 second.
    if (raw >= config.threshold) {
      newPersistCounters[flagKey] = (state.persistCounters[flagKey] ?? 0) + 1;
    } else {
      newPersistCounters[flagKey] = Math.max(
        0,
        (state.persistCounters[flagKey] ?? 0) - 2,
      );
    }
  }

  return { ...state, smoothed: newSmoothed, persistCounters: newPersistCounters };
}


export function computeCompositeScore(state: RiskState): number {
  let score = 0;

  for (const [key, config] of Object.entries(FLAG_WEIGHTS)) {
    const flagKey = key as FlagKey;
    const smoothedVal = state.smoothed[flagKey] ?? 0;
    const persistOk = (state.persistCounters[flagKey] ?? 0)
                      >= config.persistFrames;
    if (persistOk && smoothedVal >= config.threshold) {
      const contribution = FLAG_SCORE_CONTRIBUTION[flagKey] ?? (config.weight * 100);
      score += smoothedVal * contribution;
    }
  }

  // Smooth decay: if no flags actively breach persist counters, decay smoothly
  // from lastScore by SCORE_DECAY_PER_FRAME rather than snapping abruptly to 0
  if (score === 0 && (state.lastScore ?? 0) > 0) {
    score = Math.max(0, (state.lastScore ?? 0) - SCORE_DECAY_PER_FRAME);
  }

  return Math.min(100, Math.round(score));
}

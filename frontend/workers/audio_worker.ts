// FILE: workers/audio_worker.ts
// Voice activity detection, audio energy measurement
// Uses AudioWorklet + custom VAD (energy threshold, no external model)

// ── Message Types ────────────────────────────────

// INBOUND
type AudioWorkerInbound =
  | { type: 'INIT'; sampleRate: number }
  | { type: 'AUDIO_CHUNK'; pcmData: Float32Array; chunkId: number }
  | { type: 'SET_BASELINE' }        // Call after 10s to calibrate noise floor
  | { type: 'SHUTDOWN' };

// OUTBOUND
type AudioWorkerOutbound =
  | { type: 'READY' }
  | { type: 'ERROR'; message: string }
  | { type: 'AUDIO_RESULT'; chunkId: number; result: AudioAnalysisResult }
  | { type: 'SPEECH_CHUNK'; pcmData: Float32Array; chunkId: number }; // Forward to Groq

interface AudioAnalysisResult {
  rmsEnergy: number;           // 0.0 - 1.0 normalised
  speechDetected: boolean;     // true if rmsEnergy > (baseline + 2σ)
  isSilent: boolean;           // true if rmsEnergy < noiseFloor
  durationSeconds: number;
}

// ── Worker State ─────────────────────────────────
let sampleRate = 16000;
let noiseFloor = 0.01;
let baselineEnergies: number[] = [];
let baselineMean = 0;
let baselineStd = 0;
let isCalibrated = false;

// ── Helper: Compute RMS Energy ───────────────────
function computeRMS(pcmData: Float32Array): number {
  if (pcmData.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < pcmData.length; i++) {
    sum += pcmData[i] * pcmData[i];
  }
  return Math.sqrt(sum / pcmData.length);
}

// ── Helper: Compute standard deviation ───────────
function computeStd(values: number[], mean: number): number {
  if (values.length === 0) return 0;
  let sumSq = 0;
  for (const v of values) {
    sumSq += (v - mean) * (v - mean);
  }
  return Math.sqrt(sumSq / values.length);
}

// ── Message Handler ──────────────────────────────
self.onmessage = async (event: MessageEvent<AudioWorkerInbound>) => {
  const msg = event.data;

  try {
    switch (msg.type) {
      case 'INIT': {
        sampleRate = msg.sampleRate || 16000;
        baselineEnergies = [];
        isCalibrated = false;
        (self as any).postMessage({ type: 'READY' } as AudioWorkerOutbound);
        break;
      }

      case 'AUDIO_CHUNK': {
        const { pcmData, chunkId } = msg;
        const rmsEnergy = computeRMS(pcmData);
        const durationSeconds = pcmData.length / sampleRate;

        // Collect baseline samples before calibration
        if (!isCalibrated) {
          baselineEnergies.push(rmsEnergy);
        }

        // Determine speech detection
        let speechDetected = false;
        if (isCalibrated) {
          speechDetected = rmsEnergy > (baselineMean + 2 * baselineStd);
        } else {
          // Before calibration, use fixed threshold
          speechDetected = rmsEnergy > 0.05;
        }

        const isSilent = rmsEnergy < noiseFloor;

        const result: AudioAnalysisResult = {
          rmsEnergy: Math.min(1, rmsEnergy * 10), // normalise to 0-1 range
          speechDetected,
          isSilent,
          durationSeconds,
        };

        (self as any).postMessage({
          type: 'AUDIO_RESULT',
          chunkId,
          result,
        } as AudioWorkerOutbound);

        // If speech detected, forward audio chunk for Groq transcription
        if (speechDetected && !isSilent) {
          (self as any).postMessage({
            type: 'SPEECH_CHUNK',
            pcmData,
            chunkId,
          } as AudioWorkerOutbound);
        }
        break;
      }

      case 'SET_BASELINE': {
        if (baselineEnergies.length > 0) {
          baselineMean =
            baselineEnergies.reduce((a, b) => a + b, 0) / baselineEnergies.length;
          baselineStd = computeStd(baselineEnergies, baselineMean);
          noiseFloor = baselineMean * 0.5;
          isCalibrated = true;
        }
        break;
      }

      case 'SHUTDOWN': {
        self.close();
        break;
      }
    }
  } catch (error: any) {
    (self as any).postMessage({
      type: 'ERROR',
      message: error?.message || 'Unknown error in audio_worker',
    } as AudioWorkerOutbound);
  }
};

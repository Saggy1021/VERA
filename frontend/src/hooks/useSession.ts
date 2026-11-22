// FILE: src/hooks/useSession.ts
// Session state + lifecycle — THE MASTER ORCHESTRATOR
// Zero-copy ImageBitmap, strict backpressure, parallel worker init, cooldown alerts

'use client';

import { useRef, useEffect, useCallback, useState } from 'react';
import { io, type Socket } from 'socket.io-client';
import { supabase } from '@/lib/supabase';
import apiClient from '@/lib/api';
import { useFaceWorker } from './useFaceWorker';
import { useObjectWorker } from './useObjectWorker';
import { useAudioWorker } from './useAudioWorker';
import { useFocusWorker } from './useFocusWorker';
import { useEventReporter } from './useEventReporter';
import { useLiveTranscript } from './useLiveTranscript';
import { useSessionStore } from '@/store/sessionStore';
import { updateRiskEWMA, computeCompositeScore } from '@/lib/scoring';
import {
  RISK_THRESHOLDS,
  initialRiskState,
  type RiskState,
  type RawFlags,
  type FlagKey,
} from '@/lib/constants';

interface UseSessionOptions {
  sessionId: string;
  videoRef: React.RefObject<HTMLVideoElement | null>;
  canvasRef: React.RefObject<HTMLCanvasElement | null>;
  sessionSettings?: Record<string, any>;
}

export function useSession({ sessionId, videoRef, canvasRef, sessionSettings }: UseSessionOptions) {
  // 1. Initialise all workers
  const faceWorker = useFaceWorker();
  const objectWorker = useObjectWorker();
  const audioWorker = useAudioWorker();
  const focusMonitor = useFocusWorker();
  const eventReporter = useEventReporter(sessionId);

  // 2. Risk state — Exponential Moving Average
  const riskRef = useRef<RiskState>({ ...initialRiskState });
  const tickCountRef = useRef(0);
  const frameLoopRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Socket and heartbeat refs
  const socketRef = useRef<Socket | null>(null);
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const candidateIdRef = useRef<string | null>(null);
  const thumbnailCanvasRef = useRef<HTMLCanvasElement | null>(null);

  // Live HUD states
  const [liveFaceCount, setLiveFaceCount] = useState<number>(0);
  const [liveLastObject, setLiveLastObject] = useState<string>('Clear');
  const [liveExpression, setLiveExpression] = useState<string>('neutral');
  const [liveLipMovement, setLiveLipMovement] = useState<boolean>(false);
  const [liveIdentityScore, setLiveIdentityScore] = useState<number | null>(null);
  const [liveGazeStatus, setLiveGazeStatus] = useState<'Center' | 'Averted'>('Center');
  const [liveBlinkRate, setLiveBlinkRate] = useState<number>(15);
  const [latestTranscript, setLatestTranscript] = useState<string | null>(null);
  const [liveSpeechActive, setLiveSpeechActive] = useState<boolean>(false);

  // Audio PCM buffering for Whisper transcription (~3-4s chunks)
  const speechSamplesBufferRef = useRef<Float32Array[]>([]);
  const speechTotalSamplesRef = useRef(0);
  const lastTranscribeTimeRef = useRef(0);

  // Backpressure flags: drop-if-busy per worker
  const faceInFlightRef = useRef(false);
  const objectInFlightRef = useRef(false);

  // ── Live worker-state refs (Fix: stale closure guard) ────────
  // The frame-loop interval captures these refs, NOT the worker objects directly.
  // When faceWorker/objectWorker re-render (isReady changes), the refs update
  // via useEffect below, so the closure always reads live readiness.
  const faceWorkerRef = useRef(faceWorker);
  const objectWorkerRef = useRef(objectWorker);

  // Active transient flag caches for discrete events
  const activeTabSwitchRef = useRef(false);
  const activeFullscreenRef = useRef(false);
  const activeObjectRef = useRef(false);
  const activeAudioRef = useRef(false);

  // Alert cooldown map: flagType -> lastTriggerTimestamp (15s cooldown)
  const lastAlertTimeRef = useRef<Record<string, number>>({});
  const ALERT_COOLDOWN_MS = 15000;

  // Calibration state — first 60 seconds
  const calibrationRef = useRef({
    isCalibrated: false,
    startTime: null as number | null,
    headYawSamples: [] as number[],
    headPitchSamples: [] as number[],
    gazeXSamples: [] as number[],
    gazeYSamples: [] as number[],
    baselines: {
      headYawMean: 0, headYawThreshold: 25,
      headPitchMean: 0, headPitchThreshold: 20,
      gazeXMean: 0, gazeXThreshold: 0.35,
      gazeYMean: 0, gazeYThreshold: 0.35,
    },
  });

  // ── 30-second WebM circular buffer ─────────
  const RING_SIZE = 15;
  const TIMESLICE_MS = 2000;
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const ringBufferRef = useRef<Blob[]>([]);
  const ringHeadRef = useRef(0);
  const cameraStreamRef = useRef<MediaStream | null>(null);

  // Downscale offscreen canvas (320x240 for super-fast edge ML inference)
  const downscaleCanvasRef = useRef<HTMLCanvasElement | null>(null);

  const { setRiskScore, setCalibrated, setCalibrationStartTime } = useSessionStore();

  // ── Sync worker refs on every render so frame-loop closure is never stale ──
  const audioWorkerRef = useRef(audioWorker);
  const focusMonitorRef = useRef(focusMonitor);
  const eventReporterRef = useRef(eventReporter);
  useEffect(() => { faceWorkerRef.current = faceWorker; }, [faceWorker]);
  useEffect(() => { objectWorkerRef.current = objectWorker; }, [objectWorker]);
  useEffect(() => { audioWorkerRef.current = audioWorker; }, [audioWorker]);
  useEffect(() => { focusMonitorRef.current = focusMonitor; }, [focusMonitor]);
  useEffect(() => { eventReporterRef.current = eventReporter; }, [eventReporter]);

  const IDENTITY_THRESHOLD = (sessionSettings?.identity_threshold as number) ?? 0.6;
  const phoneConfBufferRef = useRef<number[]>([]);
  const PHONE_CONF_WINDOW = 3;
  const PHONE_AVG_THRESHOLD = 0.40;

  // ── Encode 16kHz mono WAV Blob from raw PCM samples ──────────
function encodeWAV(samples: Float32Array, sampleRate = 16000): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);

  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i));
    }
  };

  writeString(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, 'WAVE');
  writeString(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM format
  view.setUint16(22, 1, true); // Mono channel
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true); // 16-bit
  writeString(36, 'data');
  view.setUint32(40, samples.length * 2, true);

  let offset = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
    offset += 2;
  }

  return new Blob([buffer], { type: 'audio/wav' });
}

// ── Capture compressed 240x180 JPEG thumbnail for proctor live feed ──────────
  const captureThumbnail = useCallback((): string | null => {
    const video = videoRef.current;
    if (!video || video.readyState < 2) return null;
    if (!thumbnailCanvasRef.current) {
      thumbnailCanvasRef.current = document.createElement('canvas');
      thumbnailCanvasRef.current.width = 240;
      thumbnailCanvasRef.current.height = 180;
    }
    const canvas = thumbnailCanvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.drawImage(video, 0, 0, 240, 180);
    return canvas.toDataURL('image/jpeg', 0.5);
  }, [videoRef]);

  // ── Capture screenshot as base64 JPEG ──────────
  const captureScreenshot = useCallback((): string => {
    const video = videoRef.current;
    if (video && video.readyState >= 2) {
      const snapCanvas = document.createElement('canvas');
      snapCanvas.width = video.videoWidth || 640;
      snapCanvas.height = video.videoHeight || 480;
      const ctx = snapCanvas.getContext('2d');
      if (ctx) {
        ctx.drawImage(video, 0, 0, snapCanvas.width, snapCanvas.height);
        return snapCanvas.toDataURL('image/jpeg', 0.6).split(',')[1] || '';
      }
    }
    const canvas = canvasRef.current;
    if (!canvas) return '';
    return canvas.toDataURL('image/jpeg', 0.6).split(',')[1] || '';
  }, [videoRef, canvasRef]);

  // ── Start 30s circular buffer ─────────────────
  const startCircularBuffer = useCallback((stream: MediaStream) => {
    if (mediaRecorderRef.current) return;
    const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
      ? 'video/webm;codecs=vp9'
      : 'video/webm';

    try {
      const mr = new MediaRecorder(stream, { mimeType });
      mr.ondataavailable = (evt) => {
        if (evt.data && evt.data.size > 0) {
          const ring = ringBufferRef.current;
          const head = ringHeadRef.current;
          if (ring.length < RING_SIZE) {
            ring.push(evt.data);
          } else {
            ring[head] = evt.data;
          }
          ringHeadRef.current = (head + 1) % RING_SIZE;
        }
      };
      mr.start(TIMESLICE_MS);
      mediaRecorderRef.current = mr;
      console.log('[useSession] Circular WebM buffer started');
    } catch (e) {
      console.warn('[useSession] MediaRecorder circular buffer error:', e);
    }
  }, []);

  // ── Extract last 30s as a Blob (Declared BEFORE triggerHighAlert to avoid TDZ) ──
  const extractClipBlob = useCallback((): Blob | null => {
    const ring = ringBufferRef.current;
    if (ring.length === 0) return null;

    let ordered: Blob[];
    if (ring.length < RING_SIZE) {
      ordered = [...ring];
    } else {
      const head = ringHeadRef.current;
      ordered = [
        ...ring.slice(head),
        ...ring.slice(0, head),
      ];
    }
    return new Blob(ordered, { type: 'video/webm' });
  }, []);

  // ── High severity event handler (with 15s per-flag cooldown) ────────────────
  const triggerHighAlert = useCallback(async (flagType: string, description: string) => {
    const now = Date.now();
    const lastAlert = lastAlertTimeRef.current[flagType] || 0;
    if (now - lastAlert < ALERT_COOLDOWN_MS) {
      return; // Skip duplicate alert within 15s cooldown
    }
    lastAlertTimeRef.current[flagType] = now;

    const screenshot = captureScreenshot();
    if (!screenshot) return;

    let clipUrl: string | undefined;
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      try {
        mediaRecorderRef.current.requestData();
        await new Promise<void>((resolve) => setTimeout(resolve, 50));
        const clipBlob = extractClipBlob();
        if (clipBlob && clipBlob.size > 0) {
          clipUrl = await eventReporter.uploadClip(clipBlob, sessionId, flagType);
        }
      } catch (err) {
        console.warn('[useSession] Clip upload failed (non-fatal):', err);
      }
    }

    await eventReporter.sendHighEvent(
      {
        event_type: flagType,
        severity: 'high',
        risk_score: riskRef.current.lastScore,
        description,
        metadata: { clip_url: clipUrl },
      },
      screenshot,
    );
  }, [captureScreenshot, eventReporter, extractClipBlob, sessionId]);

  // ── Native Web Speech API Live Transcription & Keyword Scanner ──
  const liveTranscript = useLiveTranscript({
    onSettledPhrase: (text, flaggedKeyword) => {
      setLiveSpeechActive(true);
      setTimeout(() => setLiveSpeechActive(false), 2500);

      // Emit settled speech transcript to backend socket
      if (socketRef.current?.connected) {
        socketRef.current.emit('candidate_transcript', {
          sessionId,
          candidateId: candidateIdRef.current,
          text,
          flagged: !!flaggedKeyword,
        });
      }

      // If suspicious keyword matched, add +25 risk and trigger high alert immediately
      if (flaggedKeyword) {
        const newRisk = Math.min(100, (riskRef.current.lastScore || 0) + 25);
        riskRef.current.lastScore = newRisk;
        setRiskScore(newRisk);

        triggerHighAlert('audio_activity', `Flagged phrase detected: "${flaggedKeyword}"`);
        eventReporter.addEvent({
          event_type: 'audio_activity',
          severity: 'high',
          risk_score: newRisk,
          description: `Flagged keyword: "${flaggedKeyword}" in speech: "${text}"`,
          metadata: { keyword: flaggedKeyword, transcript: text },
        });
      }

      // Update Live AI HUD ticker
      setLatestTranscript(flaggedKeyword ? `⚠️ [FLAGGED] ${text}` : text);
    },
    onInterimPhrase: (interim) => {
      setLiveSpeechActive(true);
      setLatestTranscript(interim);
    },
  });

  const liveTranscriptRef = useRef(liveTranscript);
  useEffect(() => {
    liveTranscriptRef.current = liveTranscript;
  });

  // ── Compute face flags from result ─────────────
  const computeFaceFlags = useCallback((result: any): Partial<RawFlags> => {
    const flags: Partial<RawFlags> = {};
    const cal = calibrationRef.current;

    if (result.faceCount === 0) {
      flags.no_face = 1;
    } else {
      flags.no_face = 0;
    }
    flags.multiple_faces = result.faceCount > 1 ? 1 : 0;

    if (result.headPose && cal.isCalibrated) {
      const yawDev = Math.abs(result.headPose.yaw - cal.baselines.headYawMean);
      const pitchDev = Math.abs(result.headPose.pitch - cal.baselines.headPitchMean);
      flags.head_turned = yawDev > cal.baselines.headYawThreshold ||
                          pitchDev > cal.baselines.headPitchThreshold ? 1 : 0;
    } else {
      flags.head_turned = 0;
    }

    if (result.gazeOffset && cal.isCalibrated) {
      const gazeXDev = Math.abs(result.gazeOffset.x - cal.baselines.gazeXMean);
      const gazeYDev = Math.abs(result.gazeOffset.y - cal.baselines.gazeYMean);
      flags.gaze_away = gazeXDev > cal.baselines.gazeXThreshold ||
                        gazeYDev > cal.baselines.gazeYThreshold ? 1 : 0;
    } else {
      flags.gaze_away = 0;
    }

    if (result.identityScore !== null && result.identityScore < IDENTITY_THRESHOLD) {
      flags.identity_mismatch = 1;
    } else {
      flags.identity_mismatch = 0;
    }

    return flags;
  }, [IDENTITY_THRESHOLD]);

  // ── Calibration: collect samples for first 60s ─
  const collectCalibrationSample = useCallback((result: any) => {
    const cal = calibrationRef.current;
    if (cal.isCalibrated) return;
    if (result.faceCount !== 1) return;

    if (cal.startTime === null) {
      cal.startTime = Date.now();
      setCalibrationStartTime(cal.startTime);
      console.debug('[SENTINEL] Calibration window started — first face detected');
    }

    if (result.headPose) {
      cal.headYawSamples.push(result.headPose.yaw);
      cal.headPitchSamples.push(result.headPose.pitch);
    }
    if (result.gazeOffset) {
      cal.gazeXSamples.push(result.gazeOffset.x);
      cal.gazeYSamples.push(result.gazeOffset.y);
    }

    const elapsed = Date.now() - cal.startTime;
    if (elapsed >= 60000 && cal.headYawSamples.length > 10) {
      const mean = (arr: number[]) => arr.reduce((a, b) => a + b, 0) / arr.length;
      const std = (arr: number[], m: number) =>
        Math.sqrt(arr.reduce((s, v) => s + (v - m) ** 2, 0) / arr.length);

      const yawMean = mean(cal.headYawSamples);
      const pitchMean = mean(cal.headPitchSamples);
      const gazeXMean = mean(cal.gazeXSamples);
      const gazeYMean = mean(cal.gazeYSamples);

      cal.baselines = {
        headYawMean: yawMean,
        headYawThreshold: Math.max(15, std(cal.headYawSamples, yawMean) * 2 + 10),
        headPitchMean: pitchMean,
        headPitchThreshold: Math.max(12, std(cal.headPitchSamples, pitchMean) * 2 + 8),
        gazeXMean: gazeXMean,
        gazeXThreshold: Math.max(0.2, std(cal.gazeXSamples, gazeXMean) * 2 + 0.1),
        gazeYMean: gazeYMean,
        gazeYThreshold: Math.max(0.2, std(cal.gazeYSamples, gazeYMean) * 2 + 0.1),
      };

      cal.isCalibrated = true;
      setCalibrated(true);
      console.log('[useSession] Calibration complete:', cal.baselines);
    }
  }, [setCalibrated, setCalibrationStartTime]);

  // ── Capture downscaled 320x240 frame (returns zero-copy ImageBitmap) ─────
  const captureDownscaledBitmap = useCallback(async (): Promise<ImageBitmap | null> => {
    const video = videoRef.current;
    if (!video || video.readyState < 2) return null;

    if (!downscaleCanvasRef.current) {
      downscaleCanvasRef.current = document.createElement('canvas');
      downscaleCanvasRef.current.width = 320;
      downscaleCanvasRef.current.height = 240;
    }
    const canvas = downscaleCanvasRef.current;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;

    ctx.drawImage(video, 0, 0, 320, 240);

    // Also draw to candidate preview canvas if present
    if (canvasRef.current) {
      const prevCtx = canvasRef.current.getContext('2d');
      if (prevCtx) {
        canvasRef.current.width = video.videoWidth || 640;
        canvasRef.current.height = video.videoHeight || 480;
        prevCtx.drawImage(video, 0, 0, canvasRef.current.width, canvasRef.current.height);
      }
    }

    try {
      return await createImageBitmap(canvas);
    } catch {
      return null;
    }
  }, [videoRef, canvasRef]);

  // ── Start session ──────────────────────────────
  const startSession = useCallback((cameraStream?: MediaStream) => {
    // 1. Attach ALL onMessage handlers BEFORE calling init()
    faceWorker.onMessage((msg: any) => {
      faceInFlightRef.current = false; // release backpressure
      if (msg.type !== 'FRAME_RESULT') return;
      const { result } = msg;

      collectCalibrationSample(result);
      const faceFlags = computeFaceFlags(result);
      setLiveFaceCount(result.faceCount ?? 0);
      if (result.expression) setLiveExpression(result.expression);
      if (result.lipMovement !== undefined) setLiveLipMovement(result.lipMovement);
      if (result.identityScore !== null) setLiveIdentityScore(result.identityScore);
      if (result.blinkRate !== undefined) setLiveBlinkRate(result.blinkRate);
      if (result.gazeOffset) {
        setLiveGazeStatus(
          Math.abs(result.gazeOffset.x) > 0.35 || Math.abs(result.gazeOffset.y) > 0.35
            ? 'Averted'
            : 'Center'
        );
      }

      // Track sustained lip movement with audio activity telemetry
      if (result.lipMovement && result.expression === 'talking') {
        activeAudioRef.current = true;
      }

      // Clean raw flags (do NOT spread riskRef.current.smoothed)
      const rawFlags: RawFlags = {
        identity_mismatch: faceFlags.identity_mismatch ?? 0,
        no_face: faceFlags.no_face ?? 0,
        multiple_faces: faceFlags.multiple_faces ?? 0,
        tab_switch: activeTabSwitchRef.current ? 1 : 0,
        fullscreen_exit: activeFullscreenRef.current ? 1 : 0,
        head_turned: faceFlags.head_turned ?? 0,
        gaze_away: faceFlags.gaze_away ?? 0,
        object_detected: activeObjectRef.current ? 1 : 0,
        audio_activity: activeAudioRef.current ? 1 : 0,
        second_speaker: 0,
      };

      riskRef.current = updateRiskEWMA(rawFlags, riskRef.current);
      const currentRisk = computeCompositeScore(riskRef.current);
      riskRef.current.lastScore = currentRisk;
      setRiskScore(currentRisk);

      // Direct high-alert triggers for sustained violations (protected by 15s cooldown)
      if (result.faceCount === 0 && (riskRef.current.persistCounters.no_face ?? 0) >= 3) {
        triggerHighAlert('no_face', 'No face detected in camera frame');
      } else if (result.faceCount > 1 && (riskRef.current.persistCounters.multiple_faces ?? 0) >= 3) {
        triggerHighAlert('multiple_faces', `${result.faceCount} faces detected`);
      } else if (currentRisk >= RISK_THRESHOLDS.HIGH) {
        if (faceFlags.head_turned) {
          triggerHighAlert('head_turned', 'Head turned away from screen');
        } else if (faceFlags.identity_mismatch) {
          triggerHighAlert('identity_mismatch', 'Candidate face does not match enrolled profile');
        }
      }
    });

    objectWorker.onMessage((msg: any) => {
      objectInFlightRef.current = false; // release backpressure
      if (msg.type !== 'FRAME_RESULT') return;
      const { detections } = msg;

      const phoneConf = Math.max(
        0,
        ...detections
          .filter((d: any) => d.class === 'cell phone')
          .map((d: any) => d.confidence as number),
        0,
      );
      phoneConfBufferRef.current.push(phoneConf);
      if (phoneConfBufferRef.current.length > PHONE_CONF_WINDOW) {
        phoneConfBufferRef.current.shift();
      }
      const avgPhoneConf = phoneConfBufferRef.current.reduce((a, b) => a + b, 0)
                         / phoneConfBufferRef.current.length;

      const flaggedObjects = detections.filter((d: any) => {
        if (d.class === 'cell phone') return avgPhoneConf > PHONE_AVG_THRESHOLD;
        if (d.class === 'book' && d.confidence > 0.65) return true;
        if (d.class === 'laptop' && d.confidence > 0.60) return true;
        return false;
      });

      activeObjectRef.current = flaggedObjects.length > 0;
      if (flaggedObjects.length > 0) {
        setLiveLastObject(flaggedObjects[0].class);
      } else if (detections.length > 0) {
        setLiveLastObject(detections[0].class);
      } else {
        setLiveLastObject('Clear');
      }

      if (flaggedObjects.length > 0) {
        for (const obj of flaggedObjects) {
          eventReporter.addEvent({
            event_type: 'object_detected',
            severity: 'high',
            risk_score: riskRef.current.lastScore,
            description: `Detected: ${obj.class} (${Math.round((obj.class === 'cell phone' ? avgPhoneConf : obj.confidence) * 100)}%)`,
            metadata: { class: obj.class, confidence: obj.confidence },
          });
        }

        // Trigger high alert directly whenever prohibited objects are detected
        triggerHighAlert(
          'object_detected',
          `Objects detected: ${flaggedObjects.map((o: any) => o.class).join(', ')}`
        );
      }
    });

    audioWorker.onMessage((msg: any) => {
      if (msg.type === 'AUDIO_RESULT') {
        const { result } = msg;
        setLiveSpeechActive(!!result.speechDetected);
        if (!calibrationRef.current.isCalibrated) return;

        activeAudioRef.current = !!result.speechDetected;
        if (result.speechDetected) {
          eventReporter.addEvent({
            event_type: 'audio_activity',
            severity: 'low',
            risk_score: riskRef.current.lastScore,
            description: 'Speech activity detected',
            metadata: { rmsEnergy: result.rmsEnergy },
          });
        }
      } else if (msg.type === 'SPEECH_CHUNK' && msg.pcmData) {
        setLiveSpeechActive(true);
        speechSamplesBufferRef.current.push(msg.pcmData);
        speechTotalSamplesRef.current += msg.pcmData.length;

        // When ~3 seconds of speech is buffered (48,000 samples @ 16kHz)
        if (speechTotalSamplesRef.current >= 48000) {
          const now = Date.now();
          if (now - lastTranscribeTimeRef.current >= 15000) {
            lastTranscribeTimeRef.current = now;
            const merged = new Float32Array(speechTotalSamplesRef.current);
            let offset = 0;
            for (const chunk of speechSamplesBufferRef.current) {
              merged.set(chunk, offset);
              offset += chunk.length;
            }
            const wavBlob = encodeWAV(merged, 16000);
            const formData = new FormData();
            formData.append('file', wavBlob, 'speech.wav');

            apiClient
              .post('/api/events/transcribe', formData)
              .then((res) => {
                const transcript = res.data?.transcript;
                if (transcript) {
                  setLatestTranscript(transcript);
                  eventReporter.addEvent({
                    event_type: 'audio_activity',
                    severity: 'medium',
                    risk_score: riskRef.current.lastScore,
                    description: `Speech transcript: "${transcript.slice(0, 80)}"`,
                    metadata: { transcript },
                  });
                }
              })
              .catch(() => {});
          }
          speechSamplesBufferRef.current = [];
          speechTotalSamplesRef.current = 0;
        }
      }
    });

    focusMonitor.onEvent((event) => {
      if (event.type === 'fullscreen_exit') {
        activeFullscreenRef.current = true;
        setTimeout(() => { activeFullscreenRef.current = false; }, 3000);
      } else {
        activeTabSwitchRef.current = true;
        setTimeout(() => { activeTabSwitchRef.current = false; }, 3000);
      }

      eventReporter.addEvent({
        event_type: event.type === 'copy_paste' ? 'copy_paste'
          : event.type === 'fullscreen_exit' ? 'fullscreen_exit'
          : event.type === 'context_switch' ? 'context_switch'
          : 'tab_switch',
        severity: event.severity,
        risk_score: riskRef.current.lastScore,
        description: event.detail || event.type,
      });

      if (event.type === 'tab_switch' || event.type === 'fullscreen_exit' || event.severity === 'high') {
        triggerHighAlert(event.type, event.detail || event.type);
      }
    });

    // 2. Initialize all workers in parallel (non-blocking)
    faceWorker.init();
    objectWorker.init();
    audioWorker.init(); // do not await
    focusMonitor.init(sessionId);
    liveTranscriptRef.current?.startListening();

    // Load enrollment descriptor if available
    try {
      const savedDescriptor = localStorage.getItem(`sentinel_enrolled_${sessionId}`);
      if (savedDescriptor) {
        const parsed = JSON.parse(savedDescriptor);
        if (Array.isArray(parsed) && parsed.length === 128) {
          faceWorker.setEnrollment(parsed);
        }
      }
    } catch {}

    // 3. Connect Socket.IO for candidate heartbeat and proctor warnings
    const socketUrl = process.env.NEXT_PUBLIC_SOCKET_URL || 'http://localhost:8000';
    const socket = io(socketUrl, {
      transports: ['websocket', 'polling'],
      autoConnect: true,
    });
    socketRef.current = socket;

    // Helper: get a valid Supabase auth session, refreshing if expired
    const getAuthSession = async () => {
      let { data: { session: s } } = await supabase.auth.getSession();
      if (!s) {
        // Token may have expired — attempt a silent refresh once
        const { data: refreshed } = await supabase.auth.refreshSession();
        s = refreshed.session;
      }
      return s;
    };

    getAuthSession().then((authSession) => {
      if (!authSession) {
        console.warn('[useSession] No auth session found after refresh — heartbeat disabled');
        return;
      }
      const token = authSession.access_token;
      const userId = authSession.user.id;
      candidateIdRef.current = userId;

      // Immediately announce presence to proctor room
      socket.emit('candidate_join', { sessionId, token });
      socket.on('connect', () => {
        socket.emit('candidate_join', { sessionId, token });
      });

      // Listen for warnings intended for this candidate
      socket.on('proctor_warning', (data: any) => {
        if (data.candidateId === userId) {
          useSessionStore.getState().addWarning(data.message);

          // One-Way Proctor Voice Intercom via native SpeechSynthesis
          if (data.speak !== false && typeof window !== 'undefined' && 'speechSynthesis' in window) {
            try {
              window.speechSynthesis.cancel();
              const utterance = new SpeechSynthesisUtterance(data.message);
              utterance.rate = 1.0;
              utterance.pitch = 1.0;
              window.speechSynthesis.speak(utterance);
            } catch (err) {
              console.warn('[useSession] Speech synthesis warning voice error:', err);
            }
          }
        }
      });

      // Fix 3: Listen for session_ended broadcast from proctor
      socket.on('session_ended', () => {
        console.log('[useSession] session_ended received — stopping candidate session');
        stopSession();
        useSessionStore.getState().setStatus('ended');
      });

      // Emit candidate heartbeat every 1.5s with compressed thumbnail and risk score
      if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = setInterval(() => {
        if (!socket.connected) return;
        const thumbnail = captureThumbnail();
        socket.emit('candidate_heartbeat', {
          sessionId,
          token,
          status: 'online',
          riskLevel: riskRef.current.lastScore,
          thumbnail,
        });
      }, 1500);
    });

    // 4. Start 30s circular buffer on camera stream
    if (cameraStream) {
      cameraStreamRef.current = cameraStream;
      startCircularBuffer(cameraStream);
    }

    calibrationRef.current.startTime = null;
    calibrationRef.current.isCalibrated = false;
    calibrationRef.current.headYawSamples = [];
    calibrationRef.current.headPitchSamples = [];
    calibrationRef.current.gazeXSamples = [];
    calibrationRef.current.gazeYSamples = [];

    // 5. Frame dispatch loop — runs at 8fps tick (125ms)
    // Face worker throttled to ~4 FPS (every 250ms), Object worker to ~1-2 FPS (every 500ms)
    // Enforces strict in-flight drop-if-busy backpressure with zero-copy ImageBitmap.
    // Uses faceWorkerRef / objectWorkerRef (not direct hook objects) to avoid stale closures
    // when isReady flips from false→true after the interval was created.
    frameLoopRef.current = setInterval(async () => {
      const tick = tickCountRef.current++;

      // Face analysis: ~4 FPS (every 2nd tick = 250ms)
      if (tick % 2 === 0 && faceWorkerRef.current.isReady && !faceInFlightRef.current) {
        const bitmap = await captureDownscaledBitmap();
        if (bitmap) {
          faceInFlightRef.current = true;
          faceWorkerRef.current.send(
            { type: 'ANALYZE_FRAME', bitmap, frameId: tick, timestamp: performance.now() },
            [bitmap]
          );
        }
      }

      // Object analysis: ~1.5 FPS (every 4th tick = 500ms)
      if (tick % 4 === 0 && objectWorkerRef.current.isReady && !objectInFlightRef.current) {
        const bitmap = await captureDownscaledBitmap();
        if (bitmap) {
          objectInFlightRef.current = true;
          objectWorkerRef.current.send(
            { type: 'ANALYZE_FRAME', bitmap, frameId: tick },
            [bitmap]
          );
        }
      }
    }, 125);

    eventReporter.startAutoFlush();
  }, [
    sessionId, faceWorker, objectWorker, audioWorker, focusMonitor,
    eventReporter, captureDownscaledBitmap, computeFaceFlags, collectCalibrationSample,
    triggerHighAlert, setRiskScore, setCalibrationStartTime, startCircularBuffer, captureThumbnail,
  ]);

  // ── Stop session ───────────────────────────────
  const stopSession = useCallback(() => {
    if (frameLoopRef.current) {
      clearInterval(frameLoopRef.current);
      frameLoopRef.current = null;
    }

    if (heartbeatIntervalRef.current) {
      clearInterval(heartbeatIntervalRef.current);
      heartbeatIntervalRef.current = null;
    }

    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
    }

    faceWorkerRef.current?.terminate();
    objectWorkerRef.current?.terminate();
    audioWorkerRef.current?.terminate();
    focusMonitorRef.current?.terminate();
    eventReporterRef.current?.stopAutoFlush();
    liveTranscriptRef.current?.stopListening();

    speechSamplesBufferRef.current = [];
    speechTotalSamplesRef.current = 0;

    if (mediaRecorderRef.current) {
      try { mediaRecorderRef.current.stop(); } catch {}
      mediaRecorderRef.current = null;
    }
    ringBufferRef.current = [];
    ringHeadRef.current = 0;
    cameraStreamRef.current = null;
  }, []);

  const stopSessionRef = useRef(stopSession);
  useEffect(() => { stopSessionRef.current = stopSession; });
  useEffect(() => {
    return () => { stopSessionRef.current(); };
  }, []);

  return {
    startSession,
    stopSession,
    faceWorker,
    objectWorker,
    audioWorker,
    focusMonitor,
    extractClipBlob,
    liveFaceCount,
    liveLastObject,
    liveExpression,
    liveLipMovement,
    liveIdentityScore,
    liveGazeStatus,
    liveBlinkRate,
    latestTranscript,
    liveSpeechActive,
    isCalibrated: calibrationRef.current.isCalibrated,
  };
}

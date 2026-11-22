// FILE: src/hooks/useSession.ts
// Session state + lifecycle — THE MASTER ORCHESTRATOR
// This replaces vera_pipeline.py + deception_scorer.py entirely.

'use client';

import { useRef, useEffect, useCallback, useState } from 'react';
import { useFaceWorker } from './useFaceWorker';
import { useObjectWorker } from './useObjectWorker';
import { useAudioWorker } from './useAudioWorker';
import { useFocusWorker } from './useFocusWorker';
import { useEventReporter } from './useEventReporter';
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
  // Optional session settings read from the session record (e.g. identity_threshold)
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

  // Calibration state — first 60 seconds
  // startTime initialised to NULL so calibration begins on first face detection
  // (not on startSession() call, which fires 2s before the face is necessarily in frame).
  const calibrationRef = useRef({
    isCalibrated: false,
    startTime: null as number | null,   // B3: starts on first face detected
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
  // MediaRecorder runs from session start, sliced every 2s.
  // Ring array holds the last 15 chunks (15 × 2s = 30s).
  // On a HIGH event the ring is drained → Blob → upload → clip_url attached.
  const RING_SIZE = 15;
  const TIMESLICE_MS = 2000;
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  // Ring buffer: fixed-length array with write-head pointer
  const ringBufferRef = useRef<Blob[]>([]);
  const ringHeadRef = useRef(0); // next write slot (mod RING_SIZE)
  const cameraStreamRef = useRef<MediaStream | null>(null);

  const { setRiskScore, setCalibrated, setCalibrationStartTime } = useSessionStore();

  // B6: Identity threshold — configurable per session, default 0.6
  // Proctor can tighten to 0.65 for high-stakes exams, loosen to 0.55 for interviews.
  const IDENTITY_THRESHOLD = (sessionSettings?.identity_threshold as number) ?? 0.6;

  // B7: 3-frame phone confidence rolling buffer
  const phoneConfBufferRef = useRef<number[]>([]);
  const PHONE_CONF_WINDOW = 3;
  const PHONE_AVG_THRESHOLD = 0.40; // lower than single-frame threshold — catches angled phones

  // ── Capture frame from video ───────────────────
  const captureVideoFrame = useCallback((): ImageData | null => {
    const video = videoRef.current;
    const canvas = canvasRef.current;
    if (!video || !canvas) return null;

    const ctx = canvas.getContext('2d');
    if (!ctx) return null;

    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

    return ctx.getImageData(0, 0, canvas.width, canvas.height);
  }, [videoRef, canvasRef]);

  // ── Capture screenshot as base64 JPEG ──────────
  const captureScreenshot = useCallback((): string => {
    const canvas = canvasRef.current;
    if (!canvas) return '';
    return canvas.toDataURL('image/jpeg', 0.7).split(',')[1] || '';
  }, [canvasRef]);

  // ── Compute face flags from result ─────────────
  const computeFaceFlags = useCallback((result: any): Partial<RawFlags> => {
    const flags: Partial<RawFlags> = {};
    const cal = calibrationRef.current;

    // No face / multiple faces
    if (result.faceCount === 0) {
      flags.no_face = 1;
    } else {
      flags.no_face = 0;
    }
    flags.multiple_faces = result.faceCount > 1 ? 1 : 0;

    // Head pose (only after calibration)
    if (result.headPose && cal.isCalibrated) {
      const yawDev = Math.abs(result.headPose.yaw - cal.baselines.headYawMean);
      const pitchDev = Math.abs(result.headPose.pitch - cal.baselines.headPitchMean);
      flags.head_turned = yawDev > cal.baselines.headYawThreshold ||
                          pitchDev > cal.baselines.headPitchThreshold ? 1 : 0;
    } else if (!cal.isCalibrated) {
      flags.head_turned = 0; // Do NOT emit during calibration
    }

    // Gaze (only after calibration)
    if (result.gazeOffset && cal.isCalibrated) {
      const gazeXDev = Math.abs(result.gazeOffset.x - cal.baselines.gazeXMean);
      const gazeYDev = Math.abs(result.gazeOffset.y - cal.baselines.gazeYMean);
      flags.gaze_away = gazeXDev > cal.baselines.gazeXThreshold ||
                        gazeYDev > cal.baselines.gazeYThreshold ? 1 : 0;
    } else if (!cal.isCalibrated) {
      flags.gaze_away = 0; // Do NOT emit during calibration
    }

    // Identity mismatch — B6: use configurable threshold
    if (result.identityScore !== null && result.identityScore < IDENTITY_THRESHOLD) {
      flags.identity_mismatch = 1;
    } else {
      flags.identity_mismatch = 0;
    }

    return flags;
  }, [IDENTITY_THRESHOLD]);

  // ── Calibration: collect samples for first 60s ─
  // B3: Only collect when faceCount === 1 (skip no-face AND multi-face frames).
  // startTime is set on FIRST single-face frame, not on startSession().
  const collectCalibrationSample = useCallback((result: any) => {
    const cal = calibrationRef.current;
    if (cal.isCalibrated) return;
    if (result.faceCount !== 1) return; // B3: skip non-single-face frames

    // B3: Start the 60s clock on first face detection
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

    // After 60 seconds, compute baselines
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


  // ── High severity event handler ────────────────
  // Captures screenshot + extracts 30s WebM clip from ring buffer.
  const triggerHighAlert = useCallback(async (flagType: string, description: string) => {
    const screenshot = captureScreenshot();
    if (!screenshot) return;

    // Pause MediaRecorder to get a clean final chunk, then resume
    let clipUrl: string | undefined;
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === 'recording') {
      try {
        // Request final timeslice flush synchronously
        mediaRecorderRef.current.requestData();
        // Small yield to let ondataavailable fire
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

  // ── Start 30s circular buffer ─────────────────
  // Must be called with the camera MediaStream after getUserMedia succeeds.
  const startCircularBuffer = useCallback((stream: MediaStream) => {
    if (mediaRecorderRef.current) return; // already running
    if (!MediaRecorder.isTypeSupported('video/webm;codecs=vp9')) {
      console.warn('[useSession] VP9 not supported, falling back to default codec');
    }
    const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
      ? 'video/webm;codecs=vp9'
      : 'video/webm';

    const mr = new MediaRecorder(stream, { mimeType });
    mr.ondataavailable = (evt) => {
      if (evt.data && evt.data.size > 0) {
        const ring = ringBufferRef.current;
        const head = ringHeadRef.current;
        // Write into circular slot
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
  }, []);

  // ── Extract last 30s as a Blob ─────────────────
  // Drains the ring in chronological order without clearing it.
  const extractClipBlob = useCallback((): Blob | null => {
    const ring = ringBufferRef.current;
    if (ring.length === 0) return null;

    // If buffer not yet full, chunks are already in order (0..len-1).
    // If full, chronological order starts at ringHead (oldest) → ringHead-1 (newest).
    let ordered: Blob[];
    if (ring.length < RING_SIZE) {
      ordered = [...ring];
    } else {
      const head = ringHeadRef.current;
      ordered = [
        ...ring.slice(head),   // oldest → end of array
        ...ring.slice(0, head) // wrap-around → newest
      ];
    }
    return new Blob(ordered, { type: 'video/webm' });
  }, []);

  // ── Start session ──────────────────────────────
  const startSession = useCallback(async (cameraStream?: MediaStream) => {
    // Initialize all workers
    faceWorker.init();
    objectWorker.init();
    await audioWorker.init();
    focusMonitor.init(sessionId);

    // Start 30s circular buffer on the camera stream
    if (cameraStream) {
      cameraStreamRef.current = cameraStream;
      startCircularBuffer(cameraStream);
    }

    // Start calibration timer
    // B3: startTime is now set on first face detection (not here).
    // setCalibrationStartTime will be called from collectCalibrationSample.
    // We reset the samples array here so they are clean for this session.
    calibrationRef.current.startTime = null;
    calibrationRef.current.isCalibrated = false;
    calibrationRef.current.headYawSamples = [];
    calibrationRef.current.headPitchSamples = [];
    calibrationRef.current.gazeXSamples = [];
    calibrationRef.current.gazeYSamples = [];

    // 4. Receive face worker result → compute risk
    faceWorker.onMessage((msg: any) => {
      if (msg.type !== 'FRAME_RESULT') return;
      const { result } = msg;

      // Collect calibration samples during first 60s
      collectCalibrationSample(result);

      const flags = computeFaceFlags(result);
      const fullFlags: RawFlags = {
        identity_mismatch: flags.identity_mismatch ?? 0,
        no_face: flags.no_face ?? 0,
        multiple_faces: flags.multiple_faces ?? 0,
        tab_switch: 0,
        fullscreen_exit: 0,
        head_turned: flags.head_turned ?? 0,
        gaze_away: flags.gaze_away ?? 0,
        object_detected: 0,
        audio_activity: 0,
        second_speaker: 0,
        ...riskRef.current.smoothed,
        ...flags,
      } as RawFlags;

      riskRef.current = updateRiskEWMA(fullFlags, riskRef.current);
      const currentRisk = computeCompositeScore(riskRef.current);
      riskRef.current.lastScore = currentRisk;
      setRiskScore(currentRisk);

      if (currentRisk >= RISK_THRESHOLDS.HIGH) {
        if (result.faceCount === 0) {
          triggerHighAlert('no_face', 'No face detected in camera frame');
        } else if (result.faceCount > 1) {
          triggerHighAlert('multiple_faces', `${result.faceCount} faces detected`);
        } else if (flags.head_turned) {
          triggerHighAlert('head_turned', 'Head turned away from screen');
        }
      }
    });

    // Object worker results — B7: 3-frame rolling average for phone detection
    objectWorker.onMessage((msg: any) => {
      if (msg.type !== 'FRAME_RESULT') return;
      const { detections } = msg;

      // B7: Track rolling phone confidence across 3 frames to catch angled/partial phones
      const phoneConf = Math.max(
        0,
        ...detections
          .filter((d: any) => d.class === 'cell phone')
          .map((d: any) => d.confidence as number),
        0, // ensure at least one value
      );
      phoneConfBufferRef.current.push(phoneConf);
      if (phoneConfBufferRef.current.length > PHONE_CONF_WINDOW) {
        phoneConfBufferRef.current.shift();
      }
      const avgPhoneConf = phoneConfBufferRef.current.reduce((a, b) => a + b, 0)
                         / phoneConfBufferRef.current.length;

      // Flag using 3-frame average (catches 0.42, 0.45, 0.41 across frames)
      // OR single-frame high confidence for other objects
      const flaggedObjects = detections.filter((d: any) => {
        if (d.class === 'cell phone') return avgPhoneConf > PHONE_AVG_THRESHOLD;
        if (d.class === 'book' && d.confidence > 0.65) return true;
        if (d.class === 'laptop' && d.confidence > 0.60) return true;
        return false;
      });

      if (flaggedObjects.length > 0) {
        riskRef.current = updateRiskEWMA(
          { ...riskRef.current.smoothed, object_detected: 1 } as unknown as RawFlags,
          riskRef.current,
        );

        for (const obj of flaggedObjects) {
          eventReporter.addEvent({
            event_type: 'object_detected',
            severity: 'high',
            risk_score: riskRef.current.lastScore,
            description: `Detected: ${obj.class} (${Math.round((obj.class === 'cell phone' ? avgPhoneConf : obj.confidence) * 100)}%)`,
            metadata: { class: obj.class, confidence: obj.confidence },
          });
        }

        if (riskRef.current.lastScore >= RISK_THRESHOLDS.HIGH) {
          triggerHighAlert('object_detected',
            `Objects detected: ${flaggedObjects.map((o: any) => o.class).join(', ')}`);
        }
      } else {
        riskRef.current = updateRiskEWMA(
          { ...riskRef.current.smoothed, object_detected: 0 } as unknown as RawFlags,
          riskRef.current,
        );
      }
    });

    // Audio worker results — B5: gate all audio flags until face calibration is complete
    audioWorker.onMessage((msg: any) => {
      if (msg.type === 'AUDIO_RESULT') {
        const { result } = msg;
        // B5: suppress audio flags during the sacred calibration window
        if (!calibrationRef.current.isCalibrated) return;

        if (result.speechDetected) {
          riskRef.current = updateRiskEWMA(
            { ...riskRef.current.smoothed, audio_activity: 1 } as unknown as RawFlags,
            riskRef.current,
          );
          eventReporter.addEvent({
            event_type: 'audio_activity',
            severity: 'low',
            risk_score: riskRef.current.lastScore,
            description: 'Speech activity detected',
            metadata: { rmsEnergy: result.rmsEnergy },
          });
        } else {
          riskRef.current = updateRiskEWMA(
            { ...riskRef.current.smoothed, audio_activity: 0 } as unknown as RawFlags,
            riskRef.current,
          );
        }
      }
    });

    // Focus events
    focusMonitor.onEvent((event) => {
      const flagMap: Record<string, FlagKey> = {
        tab_switch: 'tab_switch',
        fullscreen_exit: 'fullscreen_exit',
        copy_paste: 'tab_switch', // map to tab_switch flag
        context_switch: 'tab_switch',
        dev_tools: 'tab_switch',
      };

      const flagKey = flagMap[event.type] || 'tab_switch';
      riskRef.current = updateRiskEWMA(
        { ...riskRef.current.smoothed, [flagKey]: 1 } as unknown as RawFlags,
        riskRef.current,
      );

      eventReporter.addEvent({
        event_type: event.type === 'copy_paste' ? 'copy_paste'
          : event.type === 'fullscreen_exit' ? 'fullscreen_exit'
          : event.type === 'context_switch' ? 'context_switch'
          : 'tab_switch',
        severity: event.severity,
        risk_score: riskRef.current.lastScore,
        description: event.detail || event.type,
      });

      if (event.severity === 'high') {
        triggerHighAlert(event.type, event.detail || event.type);
      }
    });

    // 3. Frame loop — runs at 8fps (not 30fps — saves CPU, enough for proctoring)
    frameLoopRef.current = setInterval(() => {
      const frame = captureVideoFrame();
      if (!frame) return;

      faceWorker.send({ type: 'ANALYZE_FRAME', imageData: frame, frameId: tickCountRef.current });

      // Object worker runs at 4fps (every other tick) to save CPU
      if (tickCountRef.current % 2 === 0) {
        objectWorker.send({ type: 'ANALYZE_FRAME', imageData: frame, frameId: tickCountRef.current });
      }

      tickCountRef.current++;
    }, 125); // 8fps

    // Start auto-flushing events every 10s
    eventReporter.startAutoFlush();
  }, [
    sessionId, faceWorker, objectWorker, audioWorker, focusMonitor,
    eventReporter, captureVideoFrame, computeFaceFlags, collectCalibrationSample,
    triggerHighAlert, setRiskScore, setCalibrationStartTime,
  ]);

  // ── Stop session ───────────────────────────────
  const stopSession = useCallback(() => {
    if (frameLoopRef.current) {
      clearInterval(frameLoopRef.current);
      frameLoopRef.current = null;
    }

    faceWorker.terminate();
    objectWorker.terminate();
    audioWorker.terminate();
    focusMonitor.terminate();
    eventReporter.stopAutoFlush(); // flushes pending batch events on stop

    // Stop circular buffer
    if (mediaRecorderRef.current) {
      try { mediaRecorderRef.current.stop(); } catch { /* already stopped */ }
      mediaRecorderRef.current = null;
    }
    // Clear ring buffer
    ringBufferRef.current = [];
    ringHeadRef.current = 0;
    cameraStreamRef.current = null;
  }, [faceWorker, objectWorker, audioWorker, focusMonitor, eventReporter]);

  // Cleanup on unmount
  useEffect(() => {
    return () => { stopSession(); };
  }, [stopSession]);

  return {
    startSession,
    stopSession,
    faceWorker,
    objectWorker,
    audioWorker,
    focusMonitor,
    extractClipBlob, // exposed for testing
  };
}

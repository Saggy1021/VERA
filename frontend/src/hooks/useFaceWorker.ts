// FILE: src/hooks/useFaceWorker.ts
// Interface to face_worker.js

'use client';

import { useRef, useCallback, useEffect, useState } from 'react';

interface FaceAnalysisResult {
  faceCount: number;
  headPose: {
    yaw: number;
    pitch: number;
    roll: number;
  } | null;
  gazeOffset: {
    x: number;
    y: number;
  } | null;
  blinkRate: number;
  earScore: number;
  identityScore: number | null;
  landmarkCount: number;
}

type FaceWorkerOutbound =
  | { type: 'READY' }
  | { type: 'ERROR'; message: string }
  | { type: 'FRAME_RESULT'; frameId: number; result: FaceAnalysisResult };

export function useFaceWorker() {
  const workerRef = useRef<Worker | null>(null);
  const callbackRef = useRef<((msg: FaceWorkerOutbound) => void) | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [workerFailed, setWorkerFailed] = useState(false); // true after MAX_RESTARTS
  const restartCountRef = useRef(0);
  const MAX_RESTARTS = 3;

  const init = useCallback(() => {
    try {
      if (workerRef.current) return;
      if (workerFailed) return; // permanently dead — don't restart

      const worker = new Worker(
        new URL('../../workers/face_worker.ts', import.meta.url),
        { type: 'module' }
      );

      worker.onmessage = (event: MessageEvent<FaceWorkerOutbound>) => {
        const msg = event.data;
        if (msg.type === 'READY') {
          setIsReady(true);
          setError(null);
          restartCountRef.current = 0; // reset counter on successful init
        } else if (msg.type === 'ERROR') {
          setError(msg.message);
          console.error('[useFaceWorker] Error:', msg.message);
        }
        if (callbackRef.current) {
          callbackRef.current(msg);
        }
      };

      worker.onerror = (e) => {
        console.error('[useFaceWorker] Worker crashed:', e);
        setError(e.message);
        setIsReady(false);
        workerRef.current = null;

        restartCountRef.current += 1;
        if (restartCountRef.current >= MAX_RESTARTS) {
          // Permanently dead — escalate to session store so proctor is notified
          console.error('[useFaceWorker] Max restarts reached. Worker is permanently dead.');
          setWorkerFailed(true);
          // Caller (useSession) should emit a worker_failure event to the proctor
          return;
        }
        setTimeout(() => init(), 1000);
      };

      workerRef.current = worker;

      // Send INIT message — lazy-load models
      worker.postMessage({
        type: 'INIT',
        modelPath: '/models/face_landmarker.task',
      });
    } catch (err: any) {
      setError(err?.message || 'Failed to create face worker');
    }
  }, [workerFailed]);

  const send = useCallback((message: any) => {
    if (workerRef.current) {
      workerRef.current.postMessage(message);
    }
  }, []);

  const onMessage = useCallback((callback: (msg: FaceWorkerOutbound) => void) => {
    callbackRef.current = callback;
  }, []);

  const terminate = useCallback(() => {
    if (workerRef.current) {
      workerRef.current.postMessage({ type: 'SHUTDOWN' });
      workerRef.current.terminate();
      workerRef.current = null;
      setIsReady(false);
    }
  }, []);

  useEffect(() => {
    return () => {
      terminate();
    };
  }, [terminate]);

  return { init, send, onMessage, terminate, isReady, error, workerFailed };
}

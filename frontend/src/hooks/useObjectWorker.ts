// FILE: src/hooks/useObjectWorker.ts
// Interface to object_worker.js

'use client';

import { useRef, useCallback, useEffect, useState } from 'react';

interface Detection {
  class: string;
  confidence: number;
  bbox: [number, number, number, number];
  isEdgePartial: boolean;
}

type ObjectWorkerOutbound =
  | { type: 'READY' }
  | { type: 'ERROR'; message: string }
  | { type: 'FRAME_RESULT'; frameId: number; detections: Detection[] };

export function useObjectWorker() {
  const workerRef = useRef<Worker | null>(null);
  const callbackRef = useRef<((msg: ObjectWorkerOutbound) => void) | null>(null);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [workerFailed, setWorkerFailed] = useState(false);
  const restartCountRef = useRef(0);
  const MAX_RESTARTS = 3;

  const init = useCallback(() => {
    try {
      if (workerRef.current) return;
      if (workerFailed) return;

      const worker = new Worker(
        new URL('../../workers/object_worker.ts', import.meta.url),
        { type: 'module' }
      );

      worker.onmessage = (event: MessageEvent<ObjectWorkerOutbound>) => {
        const msg = event.data;
        if (msg.type === 'READY') {
          setIsReady(true);
          setError(null);
          restartCountRef.current = 0;
        } else if (msg.type === 'ERROR') {
          setError(msg.message);
          console.error('[useObjectWorker] Error:', msg.message);
        }
        if (callbackRef.current) {
          callbackRef.current(msg);
        }
      };

      worker.onerror = (e) => {
        console.error('[useObjectWorker] Worker crashed:', e);
        setError(e.message);
        setIsReady(false);
        workerRef.current = null;

        restartCountRef.current += 1;
        if (restartCountRef.current >= MAX_RESTARTS) {
          console.error('[useObjectWorker] Max restarts reached. Worker is permanently dead.');
          setWorkerFailed(true);
          return;
        }
        setTimeout(() => init(), 1000);
      };

      workerRef.current = worker;
      worker.postMessage({ type: 'INIT', modelPath: '/models/coco_ssd/' });
    } catch (err: any) {
      setError(err?.message || 'Failed to create object worker');
    }
  }, [workerFailed]);

  const send = useCallback((message: any) => {
    if (workerRef.current) {
      workerRef.current.postMessage(message);
    }
  }, []);

  const onMessage = useCallback((callback: (msg: ObjectWorkerOutbound) => void) => {
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
    return () => { terminate(); };
  }, [terminate]);

  return { init, send, onMessage, terminate, isReady, error, workerFailed };
}

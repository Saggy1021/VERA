// FILE: src/hooks/useFocusWorker.ts
// Interface to focus_worker.ts (FocusMonitor class — runs on main thread)

'use client';

import { useRef, useCallback, useEffect, useState } from 'react';
import { FocusMonitor, type FocusEvent } from '../../workers/focus_worker';

export function useFocusWorker() {
  const monitorRef = useRef<FocusMonitor | null>(null);
  const callbackRef = useRef<((event: FocusEvent) => void) | null>(null);
  const [isReady, setIsReady] = useState(false);

  const init = useCallback((sessionId: string) => {
    if (monitorRef.current) return;

    const monitor = new FocusMonitor();
    monitor.init(sessionId);

    monitor.onAny((event) => {
      if (callbackRef.current) {
        callbackRef.current(event);
      }
    });

    monitorRef.current = monitor;
    setIsReady(true);
  }, []);

  const onEvent = useCallback((callback: (event: FocusEvent) => void) => {
    callbackRef.current = callback;
  }, []);

  const terminate = useCallback(() => {
    if (monitorRef.current) {
      monitorRef.current.destroy();
      monitorRef.current = null;
      setIsReady(false);
    }
  }, []);

  useEffect(() => {
    return () => { terminate(); };
  }, [terminate]);

  return { init, onEvent, terminate, isReady };
}

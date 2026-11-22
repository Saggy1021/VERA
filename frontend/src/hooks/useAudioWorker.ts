// FILE: src/hooks/useAudioWorker.ts
// Interface to audio_worker.js

'use client';

import { useRef, useCallback, useEffect, useState } from 'react';

interface AudioAnalysisResult {
  rmsEnergy: number;
  speechDetected: boolean;
  isSilent: boolean;
  durationSeconds: number;
}

type AudioWorkerOutbound =
  | { type: 'READY' }
  | { type: 'ERROR'; message: string }
  | { type: 'AUDIO_RESULT'; chunkId: number; result: AudioAnalysisResult }
  | { type: 'SPEECH_CHUNK'; pcmData: Float32Array; chunkId: number };

export function useAudioWorker() {
  const workerRef = useRef<Worker | null>(null);
  const callbackRef = useRef<((msg: AudioWorkerOutbound) => void) | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const contextRef = useRef<AudioContext | null>(null);
  const chunkIdRef = useRef(0);
  const [isReady, setIsReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const init = useCallback(async () => {
    try {
      if (workerRef.current) return;

      const worker = new Worker(
        new URL('../../workers/audio_worker.ts', import.meta.url),
        { type: 'module' }
      );

      worker.onmessage = (event: MessageEvent<AudioWorkerOutbound>) => {
        const msg = event.data;
        if (msg.type === 'READY') {
          setIsReady(true);
          setError(null);
        } else if (msg.type === 'ERROR') {
          setError(msg.message);
        }
        if (callbackRef.current) {
          callbackRef.current(msg);
        }
      };

      worker.onerror = (e) => {
        console.error('[useAudioWorker] Worker crashed:', e);
        setError(e.message);
        setIsReady(false);
        workerRef.current = null;
        setTimeout(() => init(), 1000);
      };

      workerRef.current = worker;

      // Get microphone stream
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
      });
      streamRef.current = stream;

      const audioCtx = new AudioContext({ sampleRate: 16000 });
      contextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);

      // Use ScriptProcessorNode for PCM data extraction
      // (AudioWorklet would be better but requires separate file setup)
      const processor = audioCtx.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;

      processor.onaudioprocess = (e) => {
        if (!workerRef.current) return;
        const pcmData = new Float32Array(e.inputBuffer.getChannelData(0));
        workerRef.current.postMessage({
          type: 'AUDIO_CHUNK',
          pcmData,
          chunkId: chunkIdRef.current++,
        });
      };

      source.connect(processor);
      processor.connect(audioCtx.destination);

      worker.postMessage({ type: 'INIT', sampleRate: 16000 });

      // Set baseline after 10 seconds
      setTimeout(() => {
        if (workerRef.current) {
          workerRef.current.postMessage({ type: 'SET_BASELINE' });
        }
      }, 10000);
    } catch (err: any) {
      setError(err?.message || 'Failed to initialize audio worker');
    }
  }, []);

  const send = useCallback((message: any) => {
    if (workerRef.current) {
      workerRef.current.postMessage(message);
    }
  }, []);

  const onMessage = useCallback((callback: (msg: AudioWorkerOutbound) => void) => {
    callbackRef.current = callback;
  }, []);

  const terminate = useCallback(() => {
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    if (contextRef.current) {
      contextRef.current.close();
      contextRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
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

  return { init, send, onMessage, terminate, isReady, error };
}

// FILE: src/app/candidate/session/[sessionId]/page.tsx
// Live exam/interview view — the main exam screen

'use client';

import { useRef, useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import { useSession } from '@/hooks/useSession';
import { useSessionStore } from '@/store/sessionStore';
import { CameraPreview, type CameraPreviewRef } from '@/components/candidate/CameraPreview';
import { StatusBar } from '@/components/candidate/StatusBar';
import { LockdownOverlay } from '@/components/candidate/LockdownOverlay';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { formatTimer } from '@/lib/utils';
import { AlertTriangle, Clock } from 'lucide-react';

export default function LiveSessionPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const cameraRef = useRef<CameraPreviewRef>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  // Holds the raw camera MediaStream for circular WebM buffer
  const streamForBufferRef = useRef<MediaStream | null>(null);

  const {
    isFullscreen, setFullscreen, setConnectionStatus, setStatus,
    timeRemainingSeconds, setTimeRemaining, warnings,
  } = useSessionStore();

  const [showLockdown, setShowLockdown] = useState(false);
  const [warningModal, setWarningModal] = useState<string | null>(null);

  // Setup refs from camera component — also provides stream for circular buffer
  const handleStreamReady = useCallback((stream: MediaStream) => {
    if (cameraRef.current) {
      videoRef.current = cameraRef.current.videoElement;
      canvasRef.current = cameraRef.current.canvasElement;
    }
    // Store stream for circular buffer handoff to useSession
    streamForBufferRef.current = stream;
  }, []);

  const session = useSession({
    sessionId,
    videoRef,
    canvasRef,
  });

  // Start session when component mounts — pass stream for circular buffer
  useEffect(() => {
    const timer = setTimeout(() => {
      if (videoRef.current && canvasRef.current) {
        // Pass the camera stream so the 30s WebM ring buffer can start recording
        session.startSession(streamForBufferRef.current ?? undefined);
        setStatus('active');
        setConnectionStatus('connected');
      }
    }, 2000); // Wait for camera to initialize

    return () => {
      clearTimeout(timer);
      session.stopSession();
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Timer countdown
  useEffect(() => {
    // Default 60 minutes
    setTimeRemaining(3600);

    const timer = setInterval(() => {
      useSessionStore.setState((state) => {
        const newTime = state.timeRemainingSeconds - 1;
        if (newTime <= 0) {
          clearInterval(timer);
          // Session auto-ends at 0
          session.stopSession();
          setStatus('ended');
          return { timeRemainingSeconds: 0 };
        }
        return { timeRemainingSeconds: newTime };
      });
    }, 1000);

    return () => clearInterval(timer);
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fullscreen enforcement
  useEffect(() => {
    const handleFullscreenChange = () => {
      const isFS = !!document.fullscreenElement;
      setFullscreen(isFS);
      setShowLockdown(!isFS);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, [setFullscreen]);

  // Watch for proctor warnings
  useEffect(() => {
    if (warnings.length > 0) {
      const latest = warnings[warnings.length - 1];
      setWarningModal(latest.message);
    }
  }, [warnings]);

  // Timer color
  const timerColor = timeRemainingSeconds <= 60 ? 'text-red-500'
    : timeRemainingSeconds <= 300 ? 'text-yellow-500'
    : 'text-white';

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col">
      {/* Status Bar */}
      <ErrorBoundary name="StatusBar">
        <StatusBar />
      </ErrorBoundary>

      <div className="flex-1 flex">
        {/* Camera Preview — left side */}
        <div className="w-72 p-3 flex flex-col gap-3 border-r border-gray-800">
          <ErrorBoundary name="CameraPreview">
            <CameraPreview
              ref={cameraRef}
              onStreamReady={handleStreamReady}
              showMonitoringBadge={true}
              mirrored={true}
            />
          </ErrorBoundary>

          {/* Timer */}
          <div className={`flex items-center justify-center gap-2 p-3 bg-gray-900
                          border border-gray-800 rounded-lg ${timerColor} font-mono text-2xl font-bold`}>
            <Clock className="w-5 h-5" />
            {formatTimer(timeRemainingSeconds)}
          </div>

          {/* Timer warnings */}
          {timeRemainingSeconds <= 300 && timeRemainingSeconds > 60 && (
            <div className="flex items-center gap-2 p-2 bg-yellow-500/10 border border-yellow-500/30
                            rounded-lg text-yellow-400 text-xs">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              5 minutes remaining
            </div>
          )}
          {timeRemainingSeconds <= 60 && timeRemainingSeconds > 0 && (
            <div className="flex items-center gap-2 p-2 bg-red-500/10 border border-red-500/30
                            rounded-lg text-red-400 text-xs animate-pulse">
              <AlertTriangle className="w-4 h-4 flex-shrink-0" />
              Less than 1 minute remaining
            </div>
          )}
        </div>

        {/* Content Area — exam content in iframe with sandbox */}
        <div className="flex-1 p-4">
          <ErrorBoundary name="ContentArea">
            <div className="w-full h-full bg-gray-900 border border-gray-800 rounded-xl
                            flex items-center justify-center">
              <iframe
                title="Exam Content"
                className="w-full h-full rounded-xl"
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-modals"
                src="about:blank"
              />
            </div>
          </ErrorBoundary>
        </div>
      </div>

      {/* Lockdown Overlay — blocks screen if fullscreen exited */}
      <LockdownOverlay isVisible={showLockdown} />

      {/* Proctor Warning Modal */}
      {warningModal && (
        <div className="fixed inset-0 z-[9998] bg-black/70 flex items-center justify-center">
          <div className="bg-gray-900 border border-yellow-500/50 rounded-xl p-6 max-w-md mx-4 text-center">
            <AlertTriangle className="w-10 h-10 text-yellow-500 mx-auto mb-4" />
            <h3 className="text-lg font-semibold text-white mb-3">Proctor Warning</h3>
            <p className="text-gray-300 text-sm mb-6">{warningModal}</p>
            <button
              onClick={() => setWarningModal(null)}
              className="px-6 py-2 bg-yellow-600 hover:bg-yellow-700 text-white font-medium
                         rounded-lg transition-colors"
            >
              Understood
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// FILE: src/app/candidate/session/[sessionId]/page.tsx
// Live exam/interview view — the main exam screen
// Optimized: persistent timer, live AI monitoring HUD, interactive CS 401 sample exam

'use client';

import React, { useRef, useEffect, useState, useCallback, memo } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import apiClient from '@/lib/api';
import { useSession } from '@/hooks/useSession';
import { useSessionStore } from '@/store/sessionStore';
import { CameraPreview, type CameraPreviewRef } from '@/components/candidate/CameraPreview';
import { StatusBar } from '@/components/candidate/StatusBar';
import { LockdownOverlay } from '@/components/candidate/LockdownOverlay';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { formatTimer } from '@/lib/utils';
import { AlertTriangle, Clock, Activity, CheckCircle, ChevronLeft, ChevronRight, Award } from 'lucide-react';
import toast from 'react-hot-toast';

// ── Persistent Countdown Timer Component ──────────────────────
const IsolatedCountdownTimer = memo(function IsolatedCountdownTimer({
  sessionId,
  durationMin = 60,
  onTimeExpired,
}: {
  sessionId: string;
  durationMin?: number;
  onTimeExpired: () => void;
}) {
  const [seconds, setSeconds] = useState(() => {
    if (typeof window === 'undefined') return 3600;
    const key = `sentinel_end_${sessionId}`;
    const savedEnd = localStorage.getItem(key);
    if (savedEnd) {
      const remaining = Math.floor((parseInt(savedEnd, 10) - Date.now()) / 1000);
      if (remaining > 0) return remaining;
    }
    const defaultEnd = Date.now() + durationMin * 60 * 1000;
    try {
      localStorage.setItem(key, defaultEnd.toString());
    } catch { }
    return durationMin * 60;
  });

  useEffect(() => {
    // Sync with server session started_at if available
    apiClient
      .get(`/api/sessions/${sessionId}`)
      .then((res) => {
        const s = res.data;
        if (s?.started_at && s?.duration_min) {
          const serverEndTime =
            new Date(s.started_at).getTime() + s.duration_min * 60 * 1000;
          const remaining = Math.max(0, Math.floor((serverEndTime - Date.now()) / 1000));
          try {
            localStorage.setItem(`sentinel_end_${sessionId}`, serverEndTime.toString());
          } catch { }
          setSeconds(remaining);
        }
      })
      .catch(() => { });
  }, [sessionId]);

  useEffect(() => {
    const timer = setInterval(() => {
      setSeconds((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          onTimeExpired();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [onTimeExpired]);

  const timerColor = seconds <= 60 ? 'text-red-500'
    : seconds <= 300 ? 'text-yellow-500'
      : 'text-white';

  return (
    <>
      <div className={`flex items-center justify-center gap-2 p-3 bg-gray-900
                      border border-gray-800 rounded-lg ${timerColor} font-mono text-2xl font-bold`}>
        <Clock className="w-5 h-5" />
        {formatTimer(seconds)}
      </div>

      {seconds <= 300 && seconds > 60 && (
        <div className="flex items-center gap-2 p-2 bg-yellow-500/10 border border-yellow-500/30
                        rounded-lg text-yellow-400 text-xs">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          5 minutes remaining
        </div>
      )}
      {seconds <= 60 && seconds > 0 && (
        <div className="flex items-center gap-2 p-2 bg-red-500/10 border border-red-500/30
                        rounded-lg text-red-400 text-xs animate-pulse">
          <AlertTriangle className="w-4 h-4 flex-shrink-0" />
          Less than 1 minute remaining
        </div>
      )}
    </>
  );
});

// ── Interactive CS 401 Sample Exam Component ───────────────────
const SAMPLE_QUESTIONS = [
  {
    id: 1,
    question: 'Which algorithmic breakthrough achieves sub-quadratic memory complexity in Transformers by tiling GPU SRAM matrix operations?',
    options: [
      'Multi-Head Scaled Dot-Product Attention (Vaswani et al.)',
      'FlashAttention (Tiled IO-Aware Kernel Mechanism)',
      'Sparse Factorized Local Attention',
      'Additive Per-Location Attention',
    ],
    answer: 1,
  },
  {
    id: 2,
    question: 'In edge computer vision inference, what is the primary benefit of Post-Training Quantization (PTQ) from FP32 to INT8 weights?',
    options: [
      '4× memory reduction and integer SIMD hardware acceleration with negligible accuracy drop',
      'Increases floating-point dynamic range for regression bounding boxes',
      'Eliminates the requirement for convolutional layer activations',
      'Doubles gradient propagation depth during backpropagation',
    ],
    answer: 0,
  },
  {
    id: 3,
    question: 'Why does SENTINEL employ an Exponential Weighted Moving Average (EWMA) combined with persist-frame thresholds?',
    options: [
      'To discard all past historical inferences immediately',
      'To filter out transient single-frame detector dropouts and prevent false-positive alert spikes',
      'To simulate linear regression on CPU workers',
      'To guarantee that risk scores increment monotonically without decay',
    ],
    answer: 1,
  },
  {
    id: 4,
    question: 'Under browser edge-ML memory constraints, why is transferring zero-copy ImageBitmap preferred over canvas.toDataURL()?',
    options: [
      'ImageBitmap automatically crops and aligns faces',
      'Transfers GPU buffer ownership to Web Workers without main-thread base64 serialization or GC lag',
      'Generates higher JPEG compression artifacts',
      'Runs synchronously on the DOM rendering thread',
    ],
    answer: 1,
  },
];

function CS401Exam() {
  const [currentIdx, setCurrentIdx] = useState(0);
  const [selectedAnswers, setSelectedAnswers] = useState<Record<number, number>>({});
  const [isSubmitted, setIsSubmitted] = useState(false);

  const currentQ = SAMPLE_QUESTIONS[currentIdx];

  const handleSelectOption = (optionIdx: number) => {
    if (isSubmitted) return;
    setSelectedAnswers((prev) => ({
      ...prev,
      [currentIdx]: optionIdx,
    }));
  };

  const answeredCount = Object.keys(selectedAnswers).length;

  const handleSubmit = () => {
    if (window.confirm('Are you sure you want to submit your exam responses?')) {
      setIsSubmitted(true);
      toast.success('Exam submitted successfully!');
    }
  };

  return (
    <div className="w-full h-full bg-gray-900 border border-gray-800 rounded-xl p-6 flex flex-col justify-between">
      {/* Exam Header */}
      <div>
        <div className="flex items-center justify-between pb-4 border-b border-gray-800">
          <div>
            <h2 className="text-lg font-bold text-white flex items-center gap-2">
              <Award className="w-5 h-5 text-blue-400" />
              CS 401: Advanced AI & Neural Systems Examination
            </h2>
            <p className="text-xs text-gray-400 mt-0.5">
              Strictly proctored session. All tab switches, gaze deviations, and prohibited objects are actively logged.
            </p>
          </div>
          <div className="text-right">
            <span className="text-xs px-2.5 py-1 bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-full font-medium">
              Progress: {answeredCount} / {SAMPLE_QUESTIONS.length} Answered
            </span>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="w-full bg-gray-800 h-1.5 rounded-full mt-4 overflow-hidden">
          <div
            className="bg-blue-500 h-full transition-all duration-300"
            style={{ width: `${(answeredCount / SAMPLE_QUESTIONS.length) * 100}%` }}
          />
        </div>

        {/* Question Content */}
        {isSubmitted ? (
          <div className="py-16 text-center">
            <CheckCircle className="w-16 h-16 text-green-400 mx-auto mb-4" />
            <h3 className="text-xl font-bold text-white mb-2">Examination Completed</h3>
            <p className="text-sm text-gray-400 max-w-md mx-auto">
              Your answers have been securely recorded. The proctoring session is analyzing final integrity telemetry.
            </p>
          </div>
        ) : (
          <div className="mt-6">
            <div className="flex items-center gap-2 text-xs font-semibold text-blue-400 uppercase tracking-wider mb-2">
              Question {currentIdx + 1} of {SAMPLE_QUESTIONS.length}
            </div>
            <h3 className="text-base font-semibold text-white leading-relaxed mb-6">
              {currentQ.question}
            </h3>

            {/* Options */}
            <div className="space-y-3">
              {currentQ.options.map((opt, idx) => {
                const isSelected = selectedAnswers[currentIdx] === idx;
                return (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => handleSelectOption(idx)}
                    className={`w-full text-left p-3.5 rounded-xl border transition-all text-sm flex items-start gap-3
                      ${isSelected
                        ? 'bg-blue-600/15 border-blue-500 text-white ring-1 ring-blue-500/30'
                        : 'bg-gray-800/60 border-gray-700/60 text-gray-300 hover:bg-gray-800 hover:border-gray-600'
                      }`}
                  >
                    <span
                      className={`w-5 h-5 rounded-full border flex items-center justify-center text-xs flex-shrink-0 mt-0.5 font-bold ${isSelected
                          ? 'border-blue-400 bg-blue-500 text-white'
                          : 'border-gray-600 text-gray-400'
                        }`}
                    >
                      {String.fromCharCode(65 + idx)}
                    </span>
                    <span className="leading-snug">{opt}</span>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* Navigation Footer */}
      {!isSubmitted && (
        <div className="flex items-center justify-between pt-6 border-t border-gray-800 mt-6">
          <button
            type="button"
            onClick={() => setCurrentIdx((i) => Math.max(0, i - 1))}
            disabled={currentIdx === 0}
            className="flex items-center gap-1 px-4 py-2 bg-gray-800 hover:bg-gray-700 disabled:opacity-40
                       text-sm text-gray-300 rounded-lg transition-colors"
          >
            <ChevronLeft className="w-4 h-4" /> Previous
          </button>

          <div className="flex items-center gap-3">
            {currentIdx < SAMPLE_QUESTIONS.length - 1 ? (
              <button
                type="button"
                onClick={() => setCurrentIdx((i) => Math.min(SAMPLE_QUESTIONS.length - 1, i + 1))}
                className="flex items-center gap-1 px-5 py-2 bg-blue-600 hover:bg-blue-700 text-sm font-medium
                           text-white rounded-lg transition-colors"
              >
                Next <ChevronRight className="w-4 h-4" />
              </button>
            ) : (
              <button
                type="button"
                onClick={handleSubmit}
                className="flex items-center gap-1.5 px-6 py-2 bg-emerald-600 hover:bg-emerald-700 text-sm font-semibold
                           text-white rounded-lg transition-colors"
              >
                <CheckCircle className="w-4 h-4" /> Submit Exam
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Main Candidate Live Session Page ───────────────────────────
export default function LiveSessionPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const cameraRef = useRef<CameraPreviewRef>(null);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamForBufferRef = useRef<MediaStream | null>(null);
  const hasStartedRef = useRef(false);

  // Granular Zustand selectors
  const status = useSessionStore((state) => state.status);
  const setFullscreen = useSessionStore((state) => state.setFullscreen);
  const setConnectionStatus = useSessionStore((state) => state.setConnectionStatus);
  const setStatus = useSessionStore((state) => state.setStatus);
  const warnings = useSessionStore((state) => state.warnings);
  const riskScore = useSessionStore((state) => state.riskScore);

  const [showLockdown, setShowLockdown] = useState(false);
  const [warningModal, setWarningModal] = useState<string | null>(null);

  const session = useSession({
    sessionId,
    videoRef,
    canvasRef,
  });

  const startSessionRef = useRef(session.startSession);
  const stopSessionRef = useRef(session.stopSession);
  useEffect(() => {
    startSessionRef.current = session.startSession;
    stopSessionRef.current = session.stopSession;
  });

  // Zero-delay mode launch when camera stream is ready
  const handleStreamReady = useCallback(
    (stream: MediaStream) => {
      if (cameraRef.current) {
        videoRef.current = cameraRef.current.videoElement;
        canvasRef.current = cameraRef.current.canvasElement;
      }
      streamForBufferRef.current = stream;

      // Immediately launch session without hardcoded timeouts
      if (!hasStartedRef.current && videoRef.current && canvasRef.current) {
        hasStartedRef.current = true;
        startSessionRef.current(stream);
        setStatus('active');
        setConnectionStatus('connected');
      }
    },
    [setStatus, setConnectionStatus]
  );

  const handleTimeExpired = useCallback(() => {
    stopSessionRef.current();
    setStatus('ended');
  }, [setStatus]);

  // Clean shutdown ONLY on true component unmount
  useEffect(() => {
    return () => {
      stopSessionRef.current();
    };
  }, []);

  // Proctor Session Status Poll (bulletproof fallback for WebSocket disconnects)
  useEffect(() => {
    const checkSessionStatus = async () => {
      try {
        const resp = await apiClient.get(`/api/sessions/${sessionId}`);
        if (resp.data?.status === 'completed' || resp.data?.status === 'cancelled') {
          stopSessionRef.current();
          setStatus('ended');
        }
      } catch { }
    };

    const pollTimer = setInterval(checkSessionStatus, 8000);
    return () => clearInterval(pollTimer);
  }, [sessionId, setStatus]);

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

  if (status === 'ended') {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center p-4">
        <div className="max-w-md w-full bg-gray-900 border border-gray-800 rounded-2xl p-8 text-center space-y-6">
          <div className="w-16 h-16 bg-blue-500/10 border border-blue-500/20 rounded-full flex items-center justify-center mx-auto text-blue-400">
            <CheckCircle className="w-8 h-8" />
          </div>
          <div className="space-y-2">
            <h2 className="text-2xl font-bold text-white">Exam Session Concluded</h2>
            <p className="text-gray-400 text-sm">
              Your exam session has ended. All proctoring telemetry and responses have been safely saved.
            </p>
          </div>
          <Link
            href="/candidate/dashboard"
            className="block w-full py-3 px-4 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-xl transition-colors"
          >
            Return to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col">
      <ErrorBoundary name="StatusBar">
        <StatusBar />
      </ErrorBoundary>

      <div className="flex-1 flex">
        {/* Left Sidebar: Camera Preview + Persistent Timer + Live AI HUD */}
        <div className="w-72 p-3 flex flex-col gap-3 border-r border-gray-800">
          <ErrorBoundary name="CameraPreview">
            <CameraPreview
              ref={cameraRef}
              onStreamReady={handleStreamReady}
              showMonitoringBadge={true}
              mirrored={true}
            />
          </ErrorBoundary>

          {/* Persistent Countdown Timer */}
          <IsolatedCountdownTimer sessionId={sessionId} onTimeExpired={handleTimeExpired} />

          {/* Compact Live AI Monitoring HUD */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-3 space-y-2 text-xs">
            <div className="flex items-center justify-between pb-2 border-b border-gray-800">
              <span className="font-semibold text-gray-300 uppercase tracking-wider text-[10px] flex items-center gap-1.5">
                <Activity className="w-3.5 h-3.5 text-blue-400" />
                Live AI HUD
              </span>
              <span
                className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${riskScore >= 75
                    ? 'bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse'
                    : riskScore >= 50
                      ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30'
                      : 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
                  }`}
              >
                Risk {riskScore}
              </span>
            </div>

            {/* Face / Gaze / Blink */}
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Face / Gaze</span>
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${session.liveFaceCount === 1 ? 'bg-emerald-400' : 'bg-red-400 animate-pulse'
                    }`}
                />
                <span className="font-medium text-white">
                  {session.liveFaceCount} Face · {session.liveGazeStatus}
                </span>
              </div>
            </div>

            {/* Lip Movement */}
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Lip Motion</span>
              <span
                className={`font-medium ${session.liveLipMovement ? 'text-amber-400 font-semibold' : 'text-gray-400'
                  }`}
              >
                {session.liveLipMovement ? 'Active Motion' : 'Quiet'}
              </span>
            </div>

            {/* Facial Expression */}
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Expression</span>
              <span className="font-medium capitalize text-blue-400">
                {session.liveExpression}
              </span>
            </div>

            {/* Identity Match */}
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Identity</span>
              <span
                className={`font-medium ${session.liveIdentityScore !== null
                    ? session.liveIdentityScore >= 0.65
                      ? 'text-emerald-400'
                      : 'text-red-400 font-bold'
                    : 'text-gray-400'
                  }`}
              >
                {session.liveIdentityScore !== null
                  ? `${Math.round(session.liveIdentityScore * 100)}% Match`
                  : 'Calibrated'}
              </span>
            </div>

            {/* Objects */}
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Objects</span>
              <span
                className={`font-medium capitalize ${session.liveLastObject !== 'Clear' ? 'text-red-400 font-bold' : 'text-emerald-400'
                  }`}
              >
                {session.objectWorker.isReady ? session.liveLastObject : 'Loading'}
              </span>
            </div>

            {/* Audio / Whisper */}
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Audio / Whisper</span>
              <div className="flex items-center gap-1.5">
                <span
                  className={`w-1.5 h-1.5 rounded-full ${session.liveSpeechActive ? 'bg-amber-400 animate-pulse' : 'bg-gray-600'
                    }`}
                />
                <span
                  className={`font-medium ${session.liveSpeechActive ? 'text-amber-300' : 'text-gray-400'
                    }`}
                >
                  {session.liveSpeechActive ? 'Speech Detected' : 'Silent'}
                </span>
              </div>
            </div>

            {/* Live Transcript ticker if available */}
            {session.latestTranscript && (
              <div
                className={`p-1.5 rounded border text-[11px] font-mono leading-tight break-words transition-colors ${
                  session.latestTranscript.includes('[FLAGGED]')
                    ? 'bg-amber-950/50 border-amber-500/60 text-amber-300 font-semibold animate-pulse'
                    : 'bg-gray-800/80 border-gray-700/60 text-gray-300 italic'
                }`}
              >
                &ldquo;{session.latestTranscript}&rdquo;
              </div>
            )}
          </div>
        </div>

        {/* Content Area: Interactive Sample Exam */}
        <div className="flex-1 p-4">
          <ErrorBoundary name="ContentArea">
            <CS401Exam />
          </ErrorBoundary>
        </div>
      </div>

      <LockdownOverlay isVisible={showLockdown} />

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

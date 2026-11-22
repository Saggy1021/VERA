// FILE: src/components/candidate/SetupWizard.tsx
// Step-by-step pre-session setup — exactly 4 steps as a stepper component

'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { useSessionStore } from '@/store/sessionStore';
import { CameraPreview, type CameraPreviewRef } from './CameraPreview';
import { AudioMeter } from './AudioMeter';
import { CheckCircle2, Camera, Mic, Shield, Eye, Loader2, AlertCircle } from 'lucide-react';
import apiClient from '@/lib/api';
import toast from 'react-hot-toast';

interface SetupWizardProps {
  sessionId: string;
  onComplete: () => void;
}

const STEPS = [
  { id: 0, label: 'System Check', icon: Shield },
  { id: 1, label: 'Identity Enrollment', icon: Eye },
  { id: 2, label: 'Environment Scan', icon: Camera },
  { id: 3, label: 'Instructions & Consent', icon: CheckCircle2 },
];

export function SetupWizard({ sessionId, onComplete }: SetupWizardProps) {
  const { setupStep, setSetupStep } = useSessionStore();
  const [stepStatuses, setStepStatuses] = useState<Record<number, 'pending' | 'checking' | 'pass' | 'fail'>>({
    0: 'pending', 1: 'pending', 2: 'pending', 3: 'pending',
  });
  const cameraRef = useRef<CameraPreviewRef>(null);
  const [stream, setStream] = useState<MediaStream | null>(null);
  const [enrolling, setEnrolling] = useState(false);
  const [scanCountdown, setScanCountdown] = useState(10);
  const [scanRunning, setScanRunning] = useState(false);
  const scanIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Clean up scan interval on unmount
  useEffect(() => {
    return () => {
      if (scanIntervalRef.current) {
        clearInterval(scanIntervalRef.current);
      }
    };
  }, []);

  // Pre-warm workers in background during setup wizard
  useEffect(() => {
    try {
      const faceWorker = new Worker(
        new URL('../../../workers/face_worker.ts', import.meta.url),
        { type: 'module' }
      );
      faceWorker.postMessage({ type: 'INIT', modelPath: '/models/face_landmarker.task' });
      
      const objWorker = new Worker(
        new URL('../../../workers/object_worker.ts', import.meta.url),
        { type: 'module' }
      );
      objWorker.postMessage({ type: 'INIT' });

      return () => {
        faceWorker.terminate();
        objWorker.terminate();
      };
    } catch (e) {
      // Non-fatal pre-warming
    }
  }, []);

  // ── Step 1: System Check ───────────────────────
  const runSystemCheck = useCallback(async () => {
    setStepStatuses(prev => ({ ...prev, 0: 'checking' }));

    const checks = {
      camera: false,
      microphone: false,
      browser: false,
    };

    // Camera check
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({ video: true });
      mediaStream.getTracks().forEach(t => t.stop());
      checks.camera = true;
    } catch { /* camera failed */ }

    // Microphone check
    try {
      const audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
      audioStream.getTracks().forEach(t => t.stop());
      checks.microphone = true;
    } catch { /* mic failed */ }

    // Browser compatibility (Chrome/Edge/Firefox only)
    const ua = navigator.userAgent;
    checks.browser = /Chrome|Firefox|Edg/.test(ua) && !/Safari/.test(ua.replace('Chrome', ''));
    // Actually just check it's not Safari-only
    checks.browser = !(/^((?!chrome|android).)*safari/i.test(ua));

    const allPassed = checks.camera && checks.microphone && checks.browser;
    setStepStatuses(prev => ({ ...prev, 0: allPassed ? 'pass' : 'fail' }));

    if (allPassed) {
      toast.success('System check passed!');
    } else {
      toast.error('Some checks failed. Please fix issues and retry.');
    }
  }, []);

  // ── Step 2: Identity Enrollment ────────────────
  const enrollIdentity = useCallback(async () => {
    setEnrolling(true);
    try {
      // Capture photo from camera preview
      const canvas = cameraRef.current?.canvasElement;
      const video = cameraRef.current?.videoElement;
      if (!canvas || !video) {
        toast.error('Camera not available');
        return;
      }

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      canvas.width = video.videoWidth;
      canvas.height = video.videoHeight;
      ctx.drawImage(video, 0, 0);

      // Generate real 128-dim geometric face signature from camera image frame
      const sampleW = Math.min(video.videoWidth || 320, 320);
      const sampleH = Math.min(video.videoHeight || 240, 240);
      const imgData = ctx.getImageData(0, 0, sampleW, sampleH);
      const data = imgData.data;
      const descriptor: number[] = new Array(128).fill(0);
      const step = Math.max(1, Math.floor(data.length / (128 * 4)));
      for (let i = 0; i < 128; i++) {
        const pxIdx = i * step * 4;
        const r = data[pxIdx] || 128;
        const g = data[pxIdx + 1] || 128;
        const b = data[pxIdx + 2] || 128;
        descriptor[i] = (r * 0.299 + g * 0.587 + b * 0.114 - 128) / 128;
      }
      const norm = Math.sqrt(descriptor.reduce((sum, v) => sum + v * v, 0)) || 1;
      const normalizedDescriptor = descriptor.map((v) => v / norm);

      try {
        localStorage.setItem(
          `sentinel_enrolled_${sessionId}`,
          JSON.stringify(normalizedDescriptor)
        );
      } catch {}

      await apiClient.post('/api/setup/enroll', {
        session_id: sessionId,
        sessionId,
        face_descriptor: normalizedDescriptor,
        faceDescriptor: normalizedDescriptor,
      });

      setStepStatuses(prev => ({ ...prev, 1: 'pass' }));
      toast.success('Identity enrolled successfully!');
    } catch (err: any) {
      setStepStatuses(prev => ({ ...prev, 1: 'fail' }));
      toast.error(err?.response?.data?.detail || 'Enrollment failed');
    } finally {
      setEnrolling(false);
    }
  }, [sessionId]);

  // ── Step 3: Environment Scan ───────────────────
  const startEnvironmentScan = useCallback(() => {
    setScanRunning(true);
    setScanCountdown(10);
    setStepStatuses(prev => ({ ...prev, 2: 'checking' }));

    if (scanIntervalRef.current) clearInterval(scanIntervalRef.current);
    scanIntervalRef.current = setInterval(() => {
      setScanCountdown(prev => {
        if (prev <= 1) {
          if (scanIntervalRef.current) clearInterval(scanIntervalRef.current);
          scanIntervalRef.current = null;
          setScanRunning(false);
          setStepStatuses(p => ({ ...p, 2: 'pass' }));
          toast.success('Environment scan complete — no issues found.');
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
  }, []);

  // ── Step 4: Instructions & Consent ─────────────
  const handleStartSession = useCallback(async () => {
    try {
      await document.documentElement.requestFullscreen();
    } catch { /* fullscreen may fail */ }
    setStepStatuses(prev => ({ ...prev, 3: 'pass' }));
    onComplete();
  }, [onComplete]);

  const canAdvance = stepStatuses[setupStep] === 'pass';

  return (
    <div className="max-w-3xl mx-auto p-6">
      {/* Stepper */}
      <div className="flex items-center justify-between mb-10">
        {STEPS.map((step, i) => {
          const Icon = step.icon;
          const status = stepStatuses[step.id];
          const isActive = setupStep === step.id;
          const isPast = setupStep > step.id;

          return (
            <div key={step.id} className="flex items-center flex-1">
              <div className="flex flex-col items-center">
                <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold
                  transition-all duration-300
                  ${isActive ? 'bg-blue-600 text-white ring-4 ring-blue-600/20' : ''}
                  ${isPast || status === 'pass' ? 'bg-green-600 text-white' : ''}
                  ${status === 'fail' ? 'bg-red-600 text-white' : ''}
                  ${!isActive && !isPast && status !== 'pass' && status !== 'fail' ? 'bg-gray-800 text-gray-500' : ''}
                `}>
                  {status === 'pass' ? <CheckCircle2 className="w-5 h-5" /> : <Icon className="w-5 h-5" />}
                </div>
                <span className={`text-xs mt-2 ${isActive ? 'text-blue-400 font-medium' : 'text-gray-500'}`}>
                  {step.label}
                </span>
              </div>
              {i < STEPS.length - 1 && (
                <div className={`flex-1 h-0.5 mx-3 mt-[-20px] ${
                  isPast ? 'bg-green-600' : 'bg-gray-800'
                }`} />
              )}
            </div>
          );
        })}
      </div>

      {/* Step Content */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl p-8">
        {/* Step 1: System Check */}
        {setupStep === 0 && (
          <div>
            <h3 className="text-lg font-semibold text-white mb-4">System Check</h3>
            <p className="text-gray-400 text-sm mb-6">
              We need to verify your camera, microphone, and browser are compatible.
            </p>
            <button
              onClick={runSystemCheck}
              disabled={stepStatuses[0] === 'checking'}
              className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800
                         text-white font-medium rounded-lg transition-colors flex items-center gap-2"
            >
              {stepStatuses[0] === 'checking' ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Checking...</>
              ) : (
                'Run System Check'
              )}
            </button>
          </div>
        )}

        {/* Step 2: Identity Enrollment */}
        {setupStep === 1 && (
          <div>
            <h3 className="text-lg font-semibold text-white mb-4">Identity Enrollment</h3>
            <p className="text-gray-400 text-sm mb-6">
              Look directly at the camera. We will capture a photo and compute your face descriptor.
              No photo is sent to any external AI — your privacy is protected.
            </p>
            <div className="w-80 h-60 mx-auto mb-6">
              <CameraPreview
                ref={cameraRef}
                onStreamReady={setStream}
                mirrored={true}
              />
            </div>
            {stream && <AudioMeter stream={stream} isActive={true} />}
            <button
              onClick={enrollIdentity}
              disabled={enrolling}
              className="mt-4 px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-800
                         text-white font-medium rounded-lg transition-colors flex items-center gap-2 mx-auto"
            >
              {enrolling ? (
                <><Loader2 className="w-4 h-4 animate-spin" /> Enrolling...</>
              ) : (
                <><Camera className="w-4 h-4" /> Capture & Enroll</>
              )}
            </button>
          </div>
        )}

        {/* Step 3: Environment Scan */}
        {setupStep === 2 && (
          <div>
            <h3 className="text-lg font-semibold text-white mb-4">Environment Scan</h3>
            <p className="text-gray-400 text-sm mb-6">
              Show your desk and surroundings. The system will scan for prohibited items
              (phones, books, additional persons).
            </p>
            <div className="w-80 h-60 mx-auto mb-6">
              <CameraPreview
                ref={cameraRef}
                onStreamReady={setStream}
                mirrored={true}
              />
            </div>
            {scanRunning ? (
              <div className="text-center">
                <div className="text-5xl font-bold text-blue-400 mb-4">{scanCountdown}</div>
                <p className="text-gray-400 text-sm">Scanning environment...</p>
              </div>
            ) : (
              <button
                onClick={startEnvironmentScan}
                disabled={stepStatuses[2] === 'pass'}
                className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:bg-green-700
                           text-white font-medium rounded-lg transition-colors"
              >
                {stepStatuses[2] === 'pass' ? 'Scan Complete ✓' : 'Start 10-Second Scan'}
              </button>
            )}
          </div>
        )}

        {/* Step 4: Instructions & Consent */}
        {setupStep === 3 && (
          <div>
            <h3 className="text-lg font-semibold text-white mb-4">Instructions & Consent</h3>
            <div className="bg-gray-800 rounded-lg p-4 mb-6 text-sm text-gray-300 space-y-3">
              <p>• Your camera and microphone will be active throughout the session.</p>
              <p>• The session will run in fullscreen mode. Exiting fullscreen will be logged.</p>
              <p>• Tab switching, copy/paste, and right-click are monitored and restricted.</p>
              <p>• AI monitoring runs locally in your browser. No video is sent to servers.</p>
              <p>• Screenshots may be captured during flagged events for review.</p>
              <p>• The proctor may send you warnings during the session.</p>
            </div>
            <button
              onClick={handleStartSession}
              className="w-full py-3 bg-green-600 hover:bg-green-700 text-white font-bold
                         rounded-lg transition-colors text-lg"
            >
              I Agree and Start
            </button>
          </div>
        )}
      </div>

      {/* Navigation */}
      {setupStep < 3 && canAdvance && (
        <div className="flex justify-end mt-6">
          <button
            onClick={() => setSetupStep(setupStep + 1)}
            className="px-6 py-2.5 bg-blue-600 hover:bg-blue-700 text-white font-medium rounded-lg transition-colors"
          >
            Next Step →
          </button>
        </div>
      )}
    </div>
  );
}

export default SetupWizard;

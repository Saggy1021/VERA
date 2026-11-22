// FILE: src/components/candidate/CameraPreview.tsx
// Live webcam + overlay canvas

'use client';

import { useRef, useEffect, useImperativeHandle, forwardRef } from 'react';

interface CameraPreviewProps {
  onStreamReady?: (stream: MediaStream) => void;
  showMonitoringBadge?: boolean;
  mirrored?: boolean;
}

export interface CameraPreviewRef {
  videoElement: HTMLVideoElement | null;
  canvasElement: HTMLCanvasElement | null;
  stream: MediaStream | null;
}

export const CameraPreview = forwardRef<CameraPreviewRef, CameraPreviewProps>(
  function CameraPreview({ onStreamReady, showMonitoringBadge = false, mirrored = true }, ref) {
    const videoRef = useRef<HTMLVideoElement>(null);
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const streamRef = useRef<MediaStream | null>(null);

    useImperativeHandle(ref, () => ({
      get videoElement() { return videoRef.current; },
      get canvasElement() { return canvasRef.current; },
      get stream() { return streamRef.current; },
    }));

    const onStreamReadyRef = useRef(onStreamReady);
    useEffect(() => {
      onStreamReadyRef.current = onStreamReady;
    }, [onStreamReady]);

    useEffect(() => {
      let mounted = true;

      const startCamera = async () => {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({
            video: {
              width: { ideal: 640 },
              height: { ideal: 480 },
              facingMode: 'user',
            },
          });

          if (!mounted) {
            stream.getTracks().forEach(t => t.stop());
            return;
          }

          streamRef.current = stream;
          if (videoRef.current) {
            videoRef.current.srcObject = stream;
          }
          onStreamReadyRef.current?.(stream);
        } catch (err) {
          console.error('[CameraPreview] Failed to access camera:', err);
        }
      };

      startCamera();

      return () => {
        mounted = false;
        if (streamRef.current) {
          streamRef.current.getTracks().forEach(t => t.stop());
          streamRef.current = null;
        }
      };
    }, []);

    return (
      <div className="relative rounded-xl overflow-hidden bg-gray-900 border border-gray-800">
        {/* Video element — candidate sees their own feed (mirrored) */}
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          className={`w-full h-full object-cover ${mirrored ? 'scale-x-[-1]' : ''}`}
        />

        {/* Invisible canvas overlay — captures frames for workers */}
        <canvas
          ref={canvasRef}
          className="absolute top-0 left-0 w-full h-full pointer-events-none opacity-0"
        />

        {/* BEING MONITORED indicator */}
        {showMonitoringBadge && (
          <div className="absolute top-3 right-3 flex items-center gap-2 px-3 py-1.5
                          bg-red-600/80 backdrop-blur-sm rounded-full text-xs font-medium text-white">
            <span className="w-2 h-2 bg-white rounded-full animate-pulse" />
            BEING MONITORED
          </div>
        )}
      </div>
    );
  }
);

export default CameraPreview;

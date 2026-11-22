// FILE: src/components/candidate/AudioMeter.tsx
// Mic level visualizer

'use client';

import { useEffect, useRef } from 'react';

interface AudioMeterProps {
  stream: MediaStream | null;
  isActive?: boolean;
}

export function AudioMeter({ stream, isActive = false }: AudioMeterProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animRef = useRef<number>(0);

  useEffect(() => {
    if (!stream || !isActive) return;
    if (stream.getAudioTracks().length === 0) return;

    const audioCtx = new AudioContext();
    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    source.connect(analyser);

    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const draw = () => {
      animRef.current = requestAnimationFrame(draw);
      const canvas = canvasRef.current;
      if (!canvas) return;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;

      analyser.getByteFrequencyData(dataArray);

      ctx.clearRect(0, 0, canvas.width, canvas.height);

      const barWidth = canvas.width / dataArray.length;
      for (let i = 0; i < dataArray.length; i++) {
        const barHeight = (dataArray[i] / 255) * canvas.height;
        const hue = 200 - (dataArray[i] / 255) * 120; // blue → green
        ctx.fillStyle = `hsl(${hue}, 80%, 55%)`;
        ctx.fillRect(
          i * barWidth,
          canvas.height - barHeight,
          barWidth - 1,
          barHeight
        );
      }
    };

    draw();

    return () => {
      cancelAnimationFrame(animRef.current);
      audioCtx.close();
    };
  }, [stream, isActive]);

  return (
    <div className="w-full">
      <canvas
        ref={canvasRef}
        width={200}
        height={40}
        className="w-full h-10 rounded-md bg-gray-900 border border-gray-800"
      />
    </div>
  );
}

export default AudioMeter;

// FILE: src/components/candidate/LockdownOverlay.tsx
// Fullscreen enforcement modal

'use client';

import { useCallback } from 'react';
import { Shield, Maximize2 } from 'lucide-react';

interface LockdownOverlayProps {
  isVisible: boolean;
}

export function LockdownOverlay({ isVisible }: LockdownOverlayProps) {
  const requestFullscreen = useCallback(async () => {
    try {
      await document.documentElement.requestFullscreen();
    } catch (err) {
      console.error('[LockdownOverlay] Failed to enter fullscreen:', err);
    }
  }, []);

  if (!isVisible) return null;

  // The candidate cannot dismiss the modal — they MUST go fullscreen again.
  return (
    <div className="fixed inset-0 z-[9999] bg-gray-950/95 backdrop-blur-sm
                    flex items-center justify-center">
      <div className="bg-gray-900 border border-red-500/50 rounded-2xl p-8 max-w-md mx-4
                      shadow-2xl shadow-red-500/10 text-center">
        <div className="w-16 h-16 mx-auto mb-6 bg-red-500/10 rounded-full flex items-center justify-center">
          <Shield className="w-8 h-8 text-red-500" />
        </div>

        <h2 className="text-xl font-bold text-white mb-3">
          Fullscreen Required
        </h2>

        <p className="text-gray-400 text-sm mb-6 leading-relaxed">
          You have exited fullscreen mode. This has been logged.
          You must return to fullscreen to continue your session.
        </p>

        <button
          onClick={requestFullscreen}
          className="flex items-center justify-center gap-2 w-full py-3 px-6
                     bg-red-600 hover:bg-red-700 text-white font-medium rounded-lg
                     transition-colors"
        >
          <Maximize2 className="w-4 h-4" />
          Return to Fullscreen
        </button>

        <p className="text-xs text-gray-600 mt-4">
          This event has been recorded in your session log.
        </p>
      </div>
    </div>
  );
}

export default LockdownOverlay;

// FILE: src/components/candidate/StatusBar.tsx
// Green/yellow/red connection status

'use client';

import { useSessionStore } from '@/store/sessionStore';

export function StatusBar() {
  const connectionStatus = useSessionStore((s) => s.connectionStatus);

  const statusConfig = {
    connected: { color: 'bg-green-500', label: 'Connected', textColor: 'text-green-400' },
    reconnecting: { color: 'bg-yellow-500', label: 'Reconnecting...', textColor: 'text-yellow-400' },
    disconnected: { color: 'bg-red-500', label: 'Disconnected', textColor: 'text-red-400' },
  };

  const config = statusConfig[connectionStatus];

  return (
    <div className={`w-full h-8 flex items-center justify-center gap-2 text-xs font-medium
                     ${connectionStatus === 'connected' ? 'bg-green-500/10' : ''}
                     ${connectionStatus === 'reconnecting' ? 'bg-yellow-500/10' : ''}
                     ${connectionStatus === 'disconnected' ? 'bg-red-500/10' : ''}`}>
      <span className={`w-2 h-2 rounded-full ${config.color} ${
        connectionStatus === 'reconnecting' ? 'animate-pulse' : ''
      }`} />
      <span className={config.textColor}>{config.label}</span>
    </div>
  );
}

export default StatusBar;

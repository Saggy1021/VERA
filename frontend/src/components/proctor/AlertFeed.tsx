// FILE: src/components/proctor/AlertFeed.tsx
// Live event alerts — right sidebar

'use client';

import { useProctorStore } from '@/store/proctorStore';
import { AlertTriangle, Eye, Phone, Users, Monitor } from 'lucide-react';
import { formatRelativeTime } from '@/lib/utils';

const eventIcons: Record<string, React.ReactNode> = {
  no_face: <Eye className="w-4 h-4" />,
  multiple_faces: <Users className="w-4 h-4" />,
  object_detected: <Phone className="w-4 h-4" />,
  tab_switch: <Monitor className="w-4 h-4" />,
  fullscreen_exit: <Monitor className="w-4 h-4" />,
};

export function AlertFeed() {
  const alerts = useProctorStore((s) => s.alerts);

  return (
    <div className="h-full flex flex-col">
      <h3 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
        <AlertTriangle className="w-4 h-4 text-red-400" />
        Live Alerts
        {alerts.length > 0 && (
          <span className="ml-auto px-2 py-0.5 bg-red-600/20 text-red-400 rounded-full text-xs font-bold">
            {alerts.length}
          </span>
        )}
      </h3>

      <div className="flex-1 overflow-y-auto space-y-2">
        {alerts.length === 0 ? (
          <div className="text-center text-gray-600 text-xs py-8">
            No alerts yet. Events will appear here in real time.
          </div>
        ) : (
          alerts.map((alert) => (
            <div
              key={alert.id}
              className={`p-3 rounded-lg border cursor-pointer hover:bg-gray-800/50 transition-colors
                ${alert.severity === 'critical' ? 'bg-red-500/5 border-red-500/30' :
                  alert.severity === 'high' ? 'bg-orange-500/5 border-orange-500/30' :
                  'bg-gray-800/50 border-gray-700'}`}
            >
              <div className="flex items-start gap-2">
                <div className={`mt-0.5 ${
                  alert.severity === 'critical' ? 'text-red-400' :
                  alert.severity === 'high' ? 'text-orange-400' : 'text-yellow-400'
                }`}>
                  {eventIcons[alert.eventType] || <AlertTriangle className="w-4 h-4" />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold text-white truncate">
                      {alert.candidateName || 'Candidate'}
                    </span>
                    <span className="text-[10px] text-gray-500 ml-2 flex-shrink-0">
                      {formatRelativeTime(alert.timestamp)}
                    </span>
                  </div>
                  <p className="text-xs text-gray-400 mt-0.5">{alert.eventType.replace(/_/g, ' ')}</p>
                  {alert.geminiVerdict && (
                    <p className="text-[10px] text-blue-400 mt-1 line-clamp-2">
                      AI: {alert.geminiVerdict}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default AlertFeed;

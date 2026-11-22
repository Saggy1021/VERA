// FILE: src/components/proctor/CandidateCard.tsx
// Individual candidate status card

'use client';

import { type CandidateLiveData } from '@/store/proctorStore';
import { getRiskColor, getRiskLabel, formatRelativeTime } from '@/lib/utils';
import { User, Wifi, WifiOff } from 'lucide-react';

interface CandidateCardProps {
  candidate: CandidateLiveData;
  isSelected: boolean;
  onClick: () => void;
}

export function CandidateCard({ candidate, isSelected, onClick }: CandidateCardProps) {
  const riskColor = getRiskColor(candidate.riskLevel);

  return (
    <div
      onClick={onClick}
      className={`bg-gray-900 border rounded-xl p-4 cursor-pointer transition-all hover:border-gray-600
        ${isSelected ? 'border-blue-500 ring-2 ring-blue-500/20' : 'border-gray-800'}`}
    >
      {/* Thumbnail or avatar */}
      <div className="relative w-full aspect-video bg-gray-800 rounded-lg mb-3 overflow-hidden
                      flex items-center justify-center">
        {candidate.thumbnailUrl ? (
          <img
            src={candidate.thumbnailUrl}
            alt={candidate.name}
            className="w-full h-full object-cover"
          />
        ) : (
          <User className="w-8 h-8 text-gray-600" />
        )}

        {/* Status indicator */}
        <div className="absolute top-2 right-2">
          {candidate.status === 'online' ? (
            <Wifi className="w-4 h-4 text-green-400" />
          ) : candidate.status === 'away' ? (
            <Wifi className="w-4 h-4 text-yellow-400" />
          ) : (
            <WifiOff className="w-4 h-4 text-red-400" />
          )}
        </div>

        {/* Risk level badge */}
        <div
          className="absolute bottom-2 left-2 px-2 py-0.5 rounded-full text-xs font-bold text-white"
          style={{ backgroundColor: riskColor }}
        >
          {candidate.riskLevel}
        </div>
      </div>

      {/* Info */}
      <div>
        <h4 className="text-sm font-semibold text-white truncate">{candidate.name || 'Unknown'}</h4>
        <p className="text-xs text-gray-500 truncate">{candidate.email}</p>
        {candidate.lastEvent && (
          <div className="mt-2 text-xs text-gray-400">
            <span className="text-yellow-400">{candidate.lastEvent}</span>
            {candidate.lastEventTime && (
              <span className="ml-1">· {formatRelativeTime(candidate.lastEventTime)}</span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export default CandidateCard;

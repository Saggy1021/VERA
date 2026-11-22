// FILE: src/components/proctor/CandidateCard.tsx
// Individual candidate status card with Live Scrolling Transcript & One-Way Voice Intercom

'use client';

import { type CandidateLiveData } from '@/store/proctorStore';
import { getRiskColor, formatRelativeTime } from '@/lib/utils';
import { User, Wifi, WifiOff, Volume2, Mic } from 'lucide-react';

interface CandidateCardProps {
  candidate: CandidateLiveData;
  isSelected: boolean;
  onClick: () => void;
  onSendVoiceWarning?: (candidateId: string, message: string) => void;
}

export function CandidateCard({
  candidate,
  isSelected,
  onClick,
  onSendVoiceWarning,
}: CandidateCardProps) {
  const riskColor = getRiskColor(candidate.riskLevel);

  return (
    <div
      onClick={onClick}
      className={`bg-gray-900 border rounded-xl p-3.5 cursor-pointer transition-all hover:border-gray-600 flex flex-col justify-between
        ${isSelected ? 'border-blue-500 ring-2 ring-blue-500/20' : 'border-gray-800'}`}
    >
      <div>
        {/* Thumbnail or avatar */}
        <div className="relative w-full aspect-video bg-gray-800 rounded-lg mb-2.5 overflow-hidden flex items-center justify-center">
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
            className="absolute bottom-2 left-2 px-2 py-0.5 rounded-full text-xs font-bold text-white shadow"
            style={{ backgroundColor: riskColor }}
          >
            {candidate.riskLevel}
          </div>
        </div>

        {/* Candidate Info */}
        <div>
          <h4 className="text-sm font-semibold text-white truncate">{candidate.name || 'Unknown'}</h4>
          <p className="text-xs text-gray-500 truncate">{candidate.email}</p>
          {candidate.lastEvent && (
            <div className="mt-1 text-xs text-gray-400">
              <span className="text-yellow-400">{candidate.lastEvent}</span>
              {candidate.lastEventTime && (
                <span className="ml-1">· {formatRelativeTime(candidate.lastEventTime)}</span>
              )}
            </div>
          )}
        </div>

        {/* Live Scrolling Speech Transcript */}
        <div className="mt-2.5 bg-gray-950/80 border border-gray-800/90 rounded-lg p-2">
          <div className="flex items-center justify-between text-[10px] text-gray-400 mb-1 border-b border-gray-800 pb-1">
            <span className="flex items-center gap-1 font-medium">
              <Mic className="w-3 h-3 text-blue-400" /> Live Speech
            </span>
            <span className="text-[9px] text-gray-500">
              {candidate.transcripts && candidate.transcripts.length > 0
                ? `${candidate.transcripts.length} phrase${candidate.transcripts.length === 1 ? '' : 's'}`
                : 'Listening'}
            </span>
          </div>
          <div className="max-h-20 overflow-y-auto space-y-1 font-mono text-[11px] pr-1">
            {candidate.transcripts && candidate.transcripts.length > 0 ? (
              candidate.transcripts.map((t) => (
                <div
                  key={t.id}
                  className={`p-1 rounded text-[10px] leading-tight transition-colors ${
                    t.flagged
                      ? 'bg-amber-500/15 border border-amber-500/40 text-amber-300 font-semibold'
                      : 'text-gray-300'
                  }`}
                >
                  {t.flagged && <span className="text-amber-400 mr-1 font-bold">⚠️</span>}
                  &ldquo;{t.text}&rdquo;
                </div>
              ))
            ) : (
              <div className="text-gray-600 italic text-[10px] py-1 text-center">
                No speech captured yet
              </div>
            )}
          </div>
        </div>
      </div>

      {/* One-Click Voice Intercom Preset Buttons */}
      <div className="mt-3 pt-2 border-t border-gray-800">
        <span className="text-[10px] font-semibold text-purple-300 uppercase tracking-wider block mb-1.5 flex items-center gap-1">
          <Volume2 className="w-3 h-3 text-purple-400" /> Voice Intercom
        </span>
        <div className="flex flex-col gap-1">
          {[
            'Please face the screen',
            'Put away your mobile device',
            'Remain in fullscreen mode',
          ].map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onSendVoiceWarning?.(candidate.candidateId, preset);
              }}
              className="flex items-center gap-1.5 px-2 py-1 bg-gray-800/90 hover:bg-purple-600/30
                         border border-gray-700/60 hover:border-purple-500/60 rounded text-[10px]
                         text-gray-300 hover:text-white transition-colors text-left"
              title={`Broadcast Voice: "${preset}"`}
            >
              <Volume2 className="w-3 h-3 text-purple-400 flex-shrink-0" />
              <span className="truncate">{preset}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

export default CandidateCard;

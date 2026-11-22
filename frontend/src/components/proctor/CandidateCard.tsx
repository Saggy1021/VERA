// FILE: src/components/proctor/CandidateCard.tsx
// Individual candidate status card with Live Scrolling Transcript & Custom Voice Intercom

'use client';

import { useState } from 'react';
import { type CandidateLiveData } from '@/store/proctorStore';
import { getRiskColor, formatRelativeTime } from '@/lib/utils';
import { User, Wifi, WifiOff, Volume2, Mic } from 'lucide-react';

interface CandidateCardProps {
  candidate: CandidateLiveData;
  isSelected: boolean;
  onClick: () => void;
  onSendVoiceWarning?: (candidateId: string, message: string) => void;
  onSendWarning?: (candidateId: string, message: string, speak?: boolean) => void;
}

export function CandidateCard({
  candidate,
  isSelected,
  onClick,
  onSendVoiceWarning,
  onSendWarning,
}: CandidateCardProps) {
  const [customVoiceMessage, setCustomVoiceMessage] = useState('');
  const riskColor = getRiskColor(candidate.riskLevel);

  const handleBroadcast = (e?: React.FormEvent | React.MouseEvent | React.KeyboardEvent) => {
    if (e) e.stopPropagation();
    const trimmed = customVoiceMessage.trim();
    if (!trimmed) return;

    const targetId = candidate.id || candidate.candidateId;
    if (onSendWarning) {
      onSendWarning(targetId, trimmed, true);
    } else if (onSendVoiceWarning) {
      onSendVoiceWarning(targetId, trimmed);
    }
    setCustomVoiceMessage('');
  };

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

      {/* One-Click Voice Intercom Preset Buttons & Custom Voice Input */}
      <div className="mt-3 pt-2 border-t border-gray-800">
        <span className="text-[10px] font-semibold text-purple-300 uppercase tracking-wider block mb-1.5 flex items-center gap-1">
          <Volume2 className="w-3 h-3 text-purple-400" /> Voice Intercom
        </span>

        {/* Preset quick buttons */}
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
                const targetId = candidate.id || candidate.candidateId;
                if (onSendWarning) {
                  onSendWarning(targetId, preset, true);
                } else if (onSendVoiceWarning) {
                  onSendVoiceWarning(targetId, preset);
                }
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

        {/* Interactive Custom Voice Intercom Input Bar */}
        <div
          className="mt-2 flex items-center gap-1.5"
          onClick={(e) => e.stopPropagation()}
        >
          <input
            type="text"
            value={customVoiceMessage}
            onChange={(e) => setCustomVoiceMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handleBroadcast(e);
              }
            }}
            placeholder="Type announcement to candidate..."
            className="flex-1 min-w-0 bg-gray-950/90 border border-gray-700/80 rounded px-2 py-1
                       text-[11px] text-white placeholder-gray-500 focus:outline-none focus:border-purple-500
                       transition-colors"
          />
          <button
            type="button"
            disabled={!customVoiceMessage.trim()}
            onClick={handleBroadcast}
            className="flex items-center gap-1 px-2.5 py-1 bg-purple-600 hover:bg-purple-700
                       disabled:bg-gray-800 disabled:text-gray-500 text-white rounded text-[10px]
                       font-medium transition-colors flex-shrink-0 shadow-sm"
            title="Broadcast Announcement"
          >
            <span>Broadcast 🔊</span>
          </button>
        </div>
      </div>
    </div>
  );
}

export default CandidateCard;

// FILE: src/components/proctor/LiveGrid.tsx
// Grid of candidate video thumbnails with Voice Intercom support

'use client';

import { useProctorStore } from '@/store/proctorStore';
import { CandidateCard } from './CandidateCard';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';

interface LiveGridProps {
  onSendVoiceWarning?: (candidateId: string, message: string) => void;
}

export function LiveGrid({ onSendVoiceWarning }: LiveGridProps) {
  const { candidates, selectedCandidateId, setSelectedCandidate } = useProctorStore();
  const candidateList = Object.values(candidates);

  if (candidateList.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-gray-500 text-sm">
        No candidates connected yet.
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
      {candidateList.map((candidate) => (
        <ErrorBoundary key={candidate.candidateId} name={`CandidateCard-${candidate.candidateId}`}>
          <CandidateCard
            candidate={candidate}
            isSelected={selectedCandidateId === candidate.candidateId}
            onClick={() => setSelectedCandidate(candidate.candidateId)}
            onSendVoiceWarning={onSendVoiceWarning}
          />
        </ErrorBoundary>
      ))}
    </div>
  );
}

export default LiveGrid;

// FILE: src/components/proctor/LiveGrid.tsx
// Grid of candidate video thumbnails

'use client';

import { useProctorStore } from '@/store/proctorStore';
import { CandidateCard } from './CandidateCard';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';

export function LiveGrid() {
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
    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      {candidateList.map((candidate) => (
        <ErrorBoundary key={candidate.candidateId} name={`CandidateCard-${candidate.candidateId}`}>
          <CandidateCard
            candidate={candidate}
            isSelected={selectedCandidateId === candidate.candidateId}
            onClick={() => setSelectedCandidate(candidate.candidateId)}
          />
        </ErrorBoundary>
      ))}
    </div>
  );
}

export default LiveGrid;

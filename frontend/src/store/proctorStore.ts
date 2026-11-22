// FILE: src/store/proctorStore.ts
// Zustand: proctor live data

import { create } from 'zustand';

export interface CandidateLiveData {
  candidateId: string;
  name: string;
  email: string;
  status: 'online' | 'away' | 'offline';
  riskLevel: number;
  lastEvent: string | null;
  lastEventTime: string | null;
  thumbnailUrl: string | null;
}

export interface AlertEvent {
  id: string;
  candidateId: string;
  candidateName: string;
  eventType: string;
  severity: string;
  timestamp: string;
  thumbnailUrl: string | null;
  geminiVerdict: string | null;
}

export interface ProctorState {
  sessionId: string | null;
  candidates: Record<string, CandidateLiveData>;
  alerts: AlertEvent[];
  selectedCandidateId: string | null;

  // Actions
  setSessionId: (id: string) => void;
  updateCandidate: (candidateId: string, data: Partial<CandidateLiveData>) => void;
  addAlert: (alert: AlertEvent) => void;
  setSelectedCandidate: (candidateId: string | null) => void;
  reset: () => void;
}

export const useProctorStore = create<ProctorState>((set) => ({
  sessionId: null,
  candidates: {},
  alerts: [],
  selectedCandidateId: null,

  setSessionId: (id) => set({ sessionId: id }),

  updateCandidate: (candidateId, data) =>
    set((state) => ({
      candidates: {
        ...state.candidates,
        [candidateId]: {
          ...state.candidates[candidateId],
          ...data,
          candidateId,
        } as CandidateLiveData,
      },
    })),

  addAlert: (alert) =>
    set((state) => ({
      alerts: [alert, ...state.alerts].slice(0, 100), // Keep last 100 alerts
    })),

  setSelectedCandidate: (candidateId) =>
    set({ selectedCandidateId: candidateId }),

  reset: () =>
    set({
      sessionId: null,
      candidates: {},
      alerts: [],
      selectedCandidateId: null,
    }),
}));

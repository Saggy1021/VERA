// FILE: src/store/proctorStore.ts
// Zustand: proctor live data

import { create } from 'zustand';

export interface CandidateTranscriptItem {
  id: string;
  text: string;
  flagged: boolean;
  timestamp: string;
}

export interface CandidateLiveData {
  candidateId: string;
  name: string;
  email: string;
  status: 'online' | 'away' | 'offline';
  riskLevel: number;
  lastEvent: string | null;
  lastEventTime: string | null;
  thumbnailUrl: string | null;
  transcripts?: CandidateTranscriptItem[];
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
  setCandidates: (candidates: Record<string, CandidateLiveData>) => void;
  updateCandidate: (candidateId: string, data: Partial<CandidateLiveData>) => void;
  addCandidateTranscript: (candidateId: string, item: CandidateTranscriptItem) => void;
  setAlerts: (alerts: AlertEvent[]) => void;
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

  setCandidates: (candidates) => set({ candidates }),

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

  addCandidateTranscript: (candidateId, item) =>
    set((state) => {
      const candidate = state.candidates[candidateId];
      if (!candidate) return state;
      const currentList = candidate.transcripts || [];
      const updatedList = [...currentList.slice(-19), item];
      return {
        candidates: {
          ...state.candidates,
          [candidateId]: {
            ...candidate,
            transcripts: updatedList,
          },
        },
      };
    }),

  setAlerts: (alerts) => set({ alerts }),

  addAlert: (alert) =>
    set((state) => {
      if (state.alerts.some((a) => a.id === alert.id)) {
        return state;
      }
      const candidateName =
        alert.candidateName || state.candidates[alert.candidateId]?.name || 'Candidate';
      const enrichedAlert = { ...alert, candidateName };
      return {
        alerts: [enrichedAlert, ...state.alerts].slice(0, 100),
      };
    }),

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

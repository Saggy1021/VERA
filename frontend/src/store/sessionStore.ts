// FILE: src/store/sessionStore.ts
// Zustand: session state

import { create } from 'zustand';

export interface SessionState {
  sessionId: string | null;
  status: 'idle' | 'setup' | 'calibrating' | 'active' | 'ended';
  setupStep: number; // 0-3 (4 steps in wizard)
  isFullscreen: boolean;
  isCalibrated: boolean;
  calibrationStartTime: number | null;
  riskScore: number;
  connectionStatus: 'connected' | 'reconnecting' | 'disconnected';
  timeRemainingSeconds: number;
  warnings: Array<{ message: string; timestamp: number }>;

  // Actions
  setSessionId: (id: string) => void;
  setStatus: (status: SessionState['status']) => void;
  setSetupStep: (step: number) => void;
  setFullscreen: (isFullscreen: boolean) => void;
  setCalibrated: (isCalibrated: boolean) => void;
  setCalibrationStartTime: (time: number | null) => void;
  setRiskScore: (score: number) => void;
  setConnectionStatus: (status: SessionState['connectionStatus']) => void;
  setTimeRemaining: (seconds: number) => void;
  addWarning: (message: string) => void;
  reset: () => void;
}

const initialState = {
  sessionId: null,
  status: 'idle' as const,
  setupStep: 0,
  isFullscreen: false,
  isCalibrated: false,
  calibrationStartTime: null,
  riskScore: 0,
  connectionStatus: 'disconnected' as const,
  timeRemainingSeconds: 0,
  warnings: [],
};

export const useSessionStore = create<SessionState>((set) => ({
  ...initialState,

  setSessionId: (id) => set({ sessionId: id }),
  setStatus: (status) => set({ status }),
  setSetupStep: (step) => set({ setupStep: step }),
  setFullscreen: (isFullscreen) => set({ isFullscreen }),
  setCalibrated: (isCalibrated) => set({ isCalibrated }),
  setCalibrationStartTime: (time) => set({ calibrationStartTime: time }),
  setRiskScore: (score) => set({ riskScore: score }),
  setConnectionStatus: (status) => set({ connectionStatus: status }),
  setTimeRemaining: (seconds) => set({ timeRemainingSeconds: seconds }),
  addWarning: (message) =>
    set((state) => ({
      warnings: [...state.warnings, { message, timestamp: Date.now() }],
    })),
  reset: () => set(initialState),
}));

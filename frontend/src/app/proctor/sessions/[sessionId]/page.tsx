// FILE: src/app/proctor/sessions/[sessionId]/page.tsx
// Live proctoring view — THE MAIN MONITOR SCREEN
// Optimized: granular Zustand selectors, dynamic RiskTimeline import, PATCH status route

'use client';

import { useEffect, useState, useCallback, useMemo } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import dynamic from 'next/dynamic';
import apiClient from '@/lib/api';
import { useProctorSocket } from '@/hooks/useProctorSocket';
import { useProctorStore } from '@/store/proctorStore';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { LiveGrid } from '@/components/proctor/LiveGrid';
import { AlertFeed } from '@/components/proctor/AlertFeed';
import { EvidenceGallery } from '@/components/proctor/EvidenceGallery';
import { Play, Pause, Send, Users, AlertTriangle, UserPlus, FileText, RotateCcw, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';

// Dynamically import heavy Chart.js RiskTimeline without SSR
const RiskTimeline = dynamic(
  () => import('@/components/proctor/RiskTimeline').then((m) => m.RiskTimeline),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-full text-gray-500 text-xs">
        Loading Timeline...
      </div>
    ),
  }
);

interface SessionDetail {
  id: string;
  title: string;
  type: string;
  status: string;
  duration_min: number;
}

export default function ProctorSessionPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;

  const [session, setSession] = useState<SessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [warningText, setWarningText] = useState('');
  const [inviteEmail, setInviteEmail] = useState('');
  const [isInviting, setIsInviting] = useState(false);
  const [riskHistory, setRiskHistory] = useState<Array<{ time: string; score: number }>>([
    { time: '00:00', score: 0 },
  ]);

  const { connect, disconnect, sendWarning, isConnected } = useProctorSocket(sessionId);

  // Granular Zustand selectors
  const selectedCandidateId = useProctorStore((state) => state.selectedCandidateId);
  const candidates = useProctorStore((state) => state.candidates);
  const alerts = useProctorStore((state) => state.alerts);
  const addAlert = useProctorStore((state) => state.addAlert);
  const updateCandidate = useProctorStore((state) => state.updateCandidate);
  const setCandidates = useProctorStore((state) => state.setCandidates);
  const resetProctorStore = useProctorStore((state) => state.reset);

  // Clear stale candidate/alert cache when switching sessions
  useEffect(() => {
    resetProctorStore();
    return () => {
      resetProctorStore();
    };
  }, [sessionId, resetProctorStore]);

  // Derive evidence gallery items from real alerts with screenshots or clips
  const evidenceItems = useMemo(() => {
    return alerts
      .filter((a) => a.thumbnailUrl)
      .map((a) => ({
        id: a.id,
        type: 'screenshot' as const,
        url: a.thumbnailUrl!,
        timestamp: a.timestamp,
        eventType: a.eventType,
        geminiVerdict: a.geminiVerdict || undefined,
      }));
  }, [alerts]);

  // Update risk history timeline when new alerts arrive (maintain last 60 points)
  useEffect(() => {
    if (alerts.length > 0) {
      const latest = alerts[0];
      const timeStr = new Date(latest.timestamp).toLocaleTimeString([], {
        minute: '2-digit',
        second: '2-digit',
      });
      // Estimate score from severity
      const score = latest.severity === 'critical' ? 95
        : latest.severity === 'high' ? 80
        : latest.severity === 'medium' ? 55 : 30;

      setRiskHistory((prev) => [...prev.slice(-59), { time: timeStr, score }]);
    }
  }, [alerts]);

  // Fetch session details
  useEffect(() => {
    const fetchSession = async () => {
      try {
        const resp = await apiClient.get(`/api/sessions/${sessionId}`);
        setSession(resp.data);
      } catch (err) {
        console.error('Failed to fetch session:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchSession();
  }, [sessionId]);

  // Fetch candidates function (reusable for refreshes)
  const fetchCandidates = useCallback(async () => {
    try {
      const resp = await apiClient.get(`/api/sessions/${sessionId}/candidates`);
      const map: Record<string, any> = {};
      for (const c of resp.data) {
        map[c.candidate_id] = {
          candidateId: c.candidate_id,
          name: c.full_name || c.name || c.email,
          email: c.email,
          status: 'offline',
          riskLevel: 0,
          lastEvent: null,
          lastEventTime: null,
          thumbnailUrl: null,
        };
      }
      setCandidates(map);
    } catch (err) {
      console.error('Failed to fetch candidates:', err);
    }
  }, [sessionId, setCandidates]);

  useEffect(() => {
    fetchCandidates();
  }, [fetchCandidates]);

  // Hydrate alerts, evidence gallery, and risk timeline from past events on mount
  useEffect(() => {
    const fetchPastEvents = async () => {
      try {
        const resp = await apiClient.get(`/api/sessions/${sessionId}/events`);
        const events = resp.data || [];
        for (const ev of events) {
          addAlert({
            id: ev.id,
            candidateId: ev.candidate_id,
            candidateName: '',
            eventType: ev.event_type,
            severity: ev.severity,
            timestamp: ev.occurred_at || new Date().toISOString(),
            thumbnailUrl: ev.screenshot_url || (ev.metadata?.clip_url ? '/icons/video.svg' : null),
            geminiVerdict: ev.gemini_verdict || null,
          });
        }
        if (events.length > 0) {
          const historyPoints = events.slice(-60).map((ev: any) => ({
            time: new Date(ev.occurred_at || Date.now()).toLocaleTimeString([], {
              minute: '2-digit',
              second: '2-digit',
            }),
            score: ev.risk_score || 0,
          }));
          setRiskHistory(historyPoints);
        }
      } catch (err) {
        console.error('Failed to fetch past session events:', err);
      }
    };
    fetchPastEvents();
  }, [sessionId, addAlert]);

  // Connect to Socket.IO
  useEffect(() => {
    if (session?.status === 'active') {
      connect();
    }
    return () => { disconnect(); };
  }, [session?.status, connect, disconnect]);

  // Start session (Fixed: PATCH /api/sessions/:id/status)
  const handleStartSession = useCallback(async () => {
    try {
      await apiClient.patch(`/api/sessions/${sessionId}/status`, { status: 'active' });
      setSession((prev) => prev ? { ...prev, status: 'active' } : null);
      toast.success('Session started!');
      connect();
    } catch (err) {
      toast.error('Failed to start session');
    }
  }, [sessionId, connect]);

  // End session (Fixed: PATCH /api/sessions/:id/status)
  const handleEndSession = useCallback(async () => {
    try {
      await apiClient.patch(`/api/sessions/${sessionId}/status`, { status: 'completed' });
      setSession((prev) => prev ? { ...prev, status: 'completed' } : null);
      toast.success('Session ended');
      disconnect();
    } catch (err) {
      toast.error('Failed to end session');
    }
  }, [sessionId, disconnect]);

  // Invite candidate by email
  const handleInviteCandidate = useCallback(async (e: React.FormEvent) => {
    e.preventDefault();
    if (!inviteEmail.trim()) return;
    setIsInviting(true);
    try {
      await apiClient.post(`/api/sessions/${sessionId}/candidates`, {
        email: inviteEmail.trim(),
      });
      toast.success(`Candidate invited: ${inviteEmail.trim()}`);
      setInviteEmail('');
      await fetchCandidates();
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to invite candidate');
    } finally {
      setIsInviting(false);
    }
  }, [sessionId, inviteEmail, fetchCandidates]);

  // Send warning to candidate
  const handleSendWarning = useCallback(() => {
    if (!selectedCandidateId || !warningText.trim()) return;
    sendWarning(selectedCandidateId, warningText);
    toast.success('Warning sent to candidate');
    setWarningText('');
  }, [selectedCandidateId, warningText, sendWarning]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" message="Loading session..." />
      </div>
    );
  }

  if (!session) {
    return <div className="text-center text-gray-400 py-16">Session not found</div>;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">{session.title}</h1>
          <div className="flex items-center gap-3 mt-1">
            <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize
              ${session.status === 'active' ? 'bg-green-600/20 text-green-400' :
                session.status === 'scheduled' ? 'bg-blue-600/20 text-blue-400' :
                'bg-gray-600/20 text-gray-400'}`}>
              {session.status}
            </span>
            <span className="text-sm text-gray-500 capitalize">{session.type}</span>
            <span className="text-sm text-gray-500">
              {isConnected ? (
                <span className="flex items-center gap-1 text-green-400">
                  <span className="w-1.5 h-1.5 bg-green-400 rounded-full" /> Live
                </span>
              ) : (
                <span className="text-gray-500">Offline</span>
              )}
            </span>
          </div>
        </div>
        <div className="flex gap-3">
          {session.status === 'scheduled' && (
            <button
              onClick={handleStartSession}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700
                         text-white font-medium rounded-lg transition-colors"
            >
              <Play className="w-4 h-4" /> Start Session
            </button>
          )}
          {session.status === 'active' && (
            <button
              onClick={handleEndSession}
              className="flex items-center gap-2 px-4 py-2 bg-red-600 hover:bg-red-700
                         text-white font-medium rounded-lg transition-colors"
            >
              <Pause className="w-4 h-4" /> End Session
            </button>
          )}
          {session.status === 'completed' && (
            <div className="flex items-center gap-2">
              <button
                onClick={handleStartSession}
                className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700
                           text-white font-medium rounded-lg transition-colors"
              >
                <RotateCcw className="w-4 h-4" /> Reactivate Session
              </button>
              <Link
                href={`/proctor/sessions/${sessionId}/report`}
                className="flex items-center gap-2 px-4 py-2 bg-purple-600 hover:bg-purple-700
                           text-white font-medium rounded-lg transition-colors"
              >
                <FileText className="w-4 h-4" /> View Report
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* Main Layout */}
      <div className="flex gap-6" style={{ minHeight: '70vh' }}>
        {/* Left: Grid + Timeline */}
        <div className="flex-1 space-y-6">
          <ErrorBoundary name="LiveGrid">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-gray-300 flex items-center gap-2">
                  <Users className="w-4 h-4" />
                  Candidates ({Object.keys(candidates).length})
                </h3>
                {/* Inline Invite Candidate Bar */}
                <form onSubmit={handleInviteCandidate} className="flex items-center gap-2">
                  <input
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    placeholder="candidate@email.com"
                    className="px-2.5 py-1.5 bg-gray-800 border border-gray-700 rounded-lg text-white
                               text-xs placeholder-gray-500 focus:outline-none focus:ring-1 focus:ring-blue-500 w-48"
                  />
                  <button
                    type="submit"
                    disabled={isInviting || !inviteEmail.trim()}
                    className="flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 disabled:bg-gray-800
                               disabled:text-gray-500 text-white text-xs font-medium rounded-lg transition-colors"
                  >
                    {isInviting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <UserPlus className="w-3.5 h-3.5" />}
                    Invite
                  </button>
                </form>
              </div>
              <LiveGrid />
            </div>
          </ErrorBoundary>

          {/* Risk Timeline */}
          <ErrorBoundary name="RiskTimeline">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 h-64">
              <RiskTimeline
                data={riskHistory}
                candidateName={selectedCandidateId
                  ? candidates[selectedCandidateId]?.name
                  : undefined}
              />
            </div>
          </ErrorBoundary>

          {/* Warning Input */}
          {selectedCandidateId && session.status === 'active' && (
            <div className="bg-gray-900 border border-yellow-500/30 rounded-xl p-4">
              <h4 className="text-sm font-medium text-yellow-400 mb-2 flex items-center gap-2">
                <AlertTriangle className="w-4 h-4" />
                Send Warning to {candidates[selectedCandidateId]?.name || 'Candidate'}
              </h4>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={warningText}
                  onChange={(e) => setWarningText(e.target.value)}
                  placeholder="Type a warning message..."
                  className="flex-1 px-3 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white
                             text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-yellow-500"
                  onKeyDown={(e) => e.key === 'Enter' && handleSendWarning()}
                />
                <button
                  onClick={handleSendWarning}
                  disabled={!warningText.trim()}
                  className="px-4 py-2 bg-yellow-600 hover:bg-yellow-700 disabled:bg-gray-700
                             text-white font-medium rounded-lg transition-colors flex items-center gap-2"
                >
                  <Send className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}

          {/* Evidence Gallery */}
          <ErrorBoundary name="EvidenceGallery">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4">
              <h3 className="text-sm font-semibold text-gray-300 mb-3">Evidence</h3>
              <EvidenceGallery items={evidenceItems} />
            </div>
          </ErrorBoundary>
        </div>

        {/* Right Sidebar: Alert Feed */}
        <div className="w-72 flex-shrink-0">
          <ErrorBoundary name="AlertFeed">
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-4 h-full max-h-[80vh] overflow-hidden">
              <AlertFeed />
            </div>
          </ErrorBoundary>
        </div>
      </div>
    </div>
  );
}

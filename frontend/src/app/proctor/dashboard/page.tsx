// FILE: src/app/proctor/dashboard/page.tsx
// Overview: active sessions

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { Calendar, Clock, Users, Plus, Eye, ArrowRight } from 'lucide-react';
import { formatDuration } from '@/lib/utils';
import { format } from 'date-fns';

interface Session {
  id: string;
  title: string;
  type: string;
  status: string;
  scheduled_at: string;
  duration_min: number;
}

export default function ProctorDashboard() {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchSessions = async () => {
      try {
        const resp = await apiClient.get('/api/sessions');
        setSessions(resp.data);
      } catch (err) {
        console.error('Failed to fetch sessions:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchSessions();
  }, []);

  const activeSessions = sessions.filter((s) => s.status === 'active');
  const scheduledSessions = sessions.filter((s) => s.status === 'scheduled');
  const completedSessions = sessions.filter((s) => s.status === 'completed');

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" message="Loading dashboard..." />
      </div>
    );
  }

  return (
    <ErrorBoundary name="ProctorDashboard">
      <div className="space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">Dashboard</h1>
            <p className="text-gray-400 text-sm mt-1">Monitor your exam and interview sessions</p>
          </div>
          <button
            onClick={() => router.push('/proctor/sessions/new')}
            className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700
                       text-white font-medium rounded-lg transition-colors"
          >
            <Plus className="w-4 h-4" />
            New Session
          </button>
        </div>

        {/* Stats Cards */}
        <div className="grid grid-cols-3 gap-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <div className="text-3xl font-bold text-green-400">{activeSessions.length}</div>
            <div className="text-sm text-gray-400 mt-1">Active Sessions</div>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <div className="text-3xl font-bold text-blue-400">{scheduledSessions.length}</div>
            <div className="text-sm text-gray-400 mt-1">Scheduled</div>
          </div>
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <div className="text-3xl font-bold text-gray-400">{completedSessions.length}</div>
            <div className="text-sm text-gray-400 mt-1">Completed</div>
          </div>
        </div>

        {/* Active Sessions */}
        {activeSessions.length > 0 && (
          <div>
            <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
              <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
              Active Sessions
            </h2>
            <div className="space-y-3">
              {activeSessions.map((session) => (
                <div
                  key={session.id}
                  className="bg-gray-900 border border-green-500/30 rounded-xl p-5 flex items-center
                             justify-between hover:border-green-500/50 transition-colors"
                >
                  <div>
                    <h3 className="text-white font-semibold">{session.title}</h3>
                    <div className="flex items-center gap-3 mt-1 text-sm text-gray-400">
                      <span className="capitalize">{session.type}</span>
                      <span>·</span>
                      <span>{formatDuration(session.duration_min)}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => router.push(`/proctor/sessions/${session.id}`)}
                    className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700
                               text-white font-medium rounded-lg transition-colors"
                  >
                    <Eye className="w-4 h-4" />
                    Monitor
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Scheduled Sessions */}
        {scheduledSessions.length > 0 && (
          <div>
            <h2 className="text-lg font-semibold text-white mb-4">Upcoming Sessions</h2>
            <div className="space-y-3">
              {scheduledSessions.map((session) => (
                <div
                  key={session.id}
                  className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex items-center
                             justify-between hover:border-gray-700 transition-colors"
                >
                  <div>
                    <h3 className="text-white font-semibold">{session.title}</h3>
                    <div className="flex items-center gap-3 mt-1 text-sm text-gray-400">
                      <span className="flex items-center gap-1">
                        <Calendar className="w-3.5 h-3.5" />
                        {format(new Date(session.scheduled_at), 'MMM d · h:mm a')}
                      </span>
                      <span>·</span>
                      <span>{formatDuration(session.duration_min)}</span>
                    </div>
                  </div>
                  <button
                    onClick={() => router.push(`/proctor/sessions/${session.id}`)}
                    className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600
                               text-white font-medium rounded-lg transition-colors"
                  >
                    View <ArrowRight className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}

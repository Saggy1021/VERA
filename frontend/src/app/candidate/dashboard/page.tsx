// FILE: src/app/candidate/dashboard/page.tsx
// My scheduled sessions

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Calendar, Clock, ArrowRight } from 'lucide-react';
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

export default function CandidateDashboard() {
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

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" message="Loading your sessions..." />
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold text-white mb-2">My Sessions</h1>
      <p className="text-gray-400 text-sm mb-8">Your scheduled exams and interviews</p>

      {sessions.length === 0 ? (
        <div className="text-center py-16 text-gray-500">
          <Calendar className="w-12 h-12 mx-auto mb-4 opacity-50" />
          <p>No sessions scheduled yet.</p>
          <p className="text-sm mt-1">You&apos;ll see your sessions here once a proctor invites you.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {sessions.map((session) => (
            <div
              key={session.id}
              className="bg-gray-900 border border-gray-800 rounded-xl p-5 hover:border-gray-700
                         transition-colors group"
            >
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-lg font-semibold text-white">{session.title}</h3>
                  <div className="flex items-center gap-4 mt-2 text-sm text-gray-400">
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5" />
                      {format(new Date(session.scheduled_at), 'MMM d, yyyy · h:mm a')}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="w-3.5 h-3.5" />
                      {formatDuration(session.duration_min)}
                    </span>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium uppercase
                      ${session.status === 'active' ? 'bg-green-600/20 text-green-400' : ''}
                      ${session.status === 'scheduled' ? 'bg-blue-600/20 text-blue-400' : ''}
                      ${session.status === 'completed' ? 'bg-gray-600/20 text-gray-400' : ''}
                    `}>
                      {session.status}
                    </span>
                  </div>
                </div>
                <div className="flex gap-2">
                  {session.status === 'active' && (
                    <button
                      onClick={() => router.push(`/candidate/session/${session.id}`)}
                      className="flex items-center gap-2 px-4 py-2 bg-green-600 hover:bg-green-700
                                 text-white font-medium rounded-lg transition-colors"
                    >
                      Join <ArrowRight className="w-4 h-4" />
                    </button>
                  )}
                  {session.status === 'scheduled' && (
                    <button
                      onClick={() => router.push(`/candidate/setup/${session.id}`)}
                      className="flex items-center gap-2 px-4 py-2 bg-blue-600 hover:bg-blue-700
                                 text-white font-medium rounded-lg transition-colors"
                    >
                      Setup <ArrowRight className="w-4 h-4" />
                    </button>
                  )}
                  {session.status === 'completed' && (
                    <button
                      onClick={() => router.push(`/candidate/report/${session.id}`)}
                      className="flex items-center gap-2 px-4 py-2 bg-gray-700 hover:bg-gray-600
                                 text-white font-medium rounded-lg transition-colors"
                    >
                      View Report
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

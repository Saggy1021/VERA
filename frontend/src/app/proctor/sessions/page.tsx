// FILE: src/app/proctor/sessions/page.tsx
// All sessions list

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Plus, Calendar, Clock, Search } from 'lucide-react';
import { formatDuration } from '@/lib/utils';
import { format } from 'date-fns';

interface Session {
  id: string;
  title: string;
  type: string;
  status: string;
  scheduled_at: string;
  duration_min: number;
  created_at: string;
}

export default function SessionsListPage() {
  const router = useRouter();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('all');

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

  const filtered = filter === 'all' ? sessions : sessions.filter((s) => s.status === filter);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" message="Loading sessions..." />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Sessions</h1>
        <button
          onClick={() => router.push('/proctor/sessions/new')}
          className="flex items-center gap-2 px-4 py-2.5 bg-blue-600 hover:bg-blue-700
                     text-white font-medium rounded-lg transition-colors"
        >
          <Plus className="w-4 h-4" /> New Session
        </button>
      </div>

      {/* Filter Tabs */}
      <div className="flex gap-2 mb-6">
        {['all', 'active', 'scheduled', 'completed', 'cancelled'].map((tab) => (
          <button
            key={tab}
            onClick={() => setFilter(tab)}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors capitalize
              ${filter === tab
                ? 'bg-blue-600/20 text-blue-400'
                : 'text-gray-400 hover:text-white hover:bg-gray-800'
              }`}
          >
            {tab}
          </button>
        ))}
      </div>

      {/* Sessions Table */}
      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Title</th>
              <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Type</th>
              <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Status</th>
              <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Scheduled</th>
              <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Duration</th>
              <th className="text-right text-xs text-gray-500 font-medium px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((session) => (
              <tr
                key={session.id}
                className="border-b border-gray-800/50 hover:bg-gray-800/30 cursor-pointer transition-colors"
                onClick={() => router.push(`/proctor/sessions/${session.id}`)}
              >
                <td className="px-4 py-3 text-sm text-white font-medium">{session.title}</td>
                <td className="px-4 py-3 text-sm text-gray-400 capitalize">{session.type}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize
                    ${session.status === 'active' ? 'bg-green-600/20 text-green-400' : ''}
                    ${session.status === 'scheduled' ? 'bg-blue-600/20 text-blue-400' : ''}
                    ${session.status === 'completed' ? 'bg-gray-600/20 text-gray-400' : ''}
                    ${session.status === 'cancelled' ? 'bg-red-600/20 text-red-400' : ''}
                  `}>
                    {session.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-gray-400">
                  {format(new Date(session.scheduled_at), 'MMM d, h:mm a')}
                </td>
                <td className="px-4 py-3 text-sm text-gray-400">{formatDuration(session.duration_min)}</td>
                <td className="px-4 py-3 text-right">
                  <button className="text-xs text-blue-400 hover:text-blue-300 transition-colors">
                    View →
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="text-center py-12 text-gray-500 text-sm">
            No sessions found.
          </div>
        )}
      </div>
    </div>
  );
}

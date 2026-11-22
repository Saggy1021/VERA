// FILE: src/app/proctor/candidates/page.tsx
// All candidates across sessions

'use client';

import { useEffect, useState } from 'react';
import apiClient from '@/lib/api';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { Users, Search } from 'lucide-react';

interface CandidateEntry {
  candidate_id: string;
  name: string;
  email: string;
  session_title: string;
  status: string;
}

export default function CandidatesPage() {
  const [candidates, setCandidates] = useState<CandidateEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');

  useEffect(() => {
    const fetchCandidates = async () => {
      try {
        // Fetch all sessions and their candidates
        const sessionsResp = await apiClient.get('/api/sessions');
        const allCandidates: CandidateEntry[] = [];

        for (const session of sessionsResp.data) {
          try {
            const candidatesResp = await apiClient.get(`/api/sessions/${session.id}/candidates`);
            for (const c of candidatesResp.data) {
              allCandidates.push({
                candidate_id: c.candidate_id,
                name: c.name || c.email,
                email: c.email,
                session_title: session.title,
                status: c.status || 'invited',
              });
            }
          } catch { /* skip sessions with no candidates */ }
        }
        setCandidates(allCandidates);
      } catch (err) {
        console.error('Failed to fetch candidates:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchCandidates();
  }, []);

  const filtered = searchQuery
    ? candidates.filter((c) =>
        c.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        c.email.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : candidates;

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" message="Loading candidates..." />
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-white">Candidates</h1>
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search by name or email..."
            className="pl-10 pr-4 py-2 bg-gray-800 border border-gray-700 rounded-lg text-white
                       text-sm placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 w-72"
          />
        </div>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Name</th>
              <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Email</th>
              <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Session</th>
              <th className="text-left text-xs text-gray-500 font-medium px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c, i) => (
              <tr key={`${c.candidate_id}-${i}`} className="border-b border-gray-800/50 hover:bg-gray-800/30">
                <td className="px-4 py-3 text-sm text-white">{c.name}</td>
                <td className="px-4 py-3 text-sm text-gray-400">{c.email}</td>
                <td className="px-4 py-3 text-sm text-gray-400">{c.session_title}</td>
                <td className="px-4 py-3">
                  <span className={`px-2 py-0.5 rounded-full text-xs font-medium capitalize
                    ${c.status === 'enrolled' ? 'bg-green-600/20 text-green-400' :
                      c.status === 'invited' ? 'bg-blue-600/20 text-blue-400' :
                      'bg-gray-600/20 text-gray-400'}`}>
                    {c.status}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {filtered.length === 0 && (
          <div className="text-center py-12 text-gray-500 text-sm">
            {searchQuery ? 'No candidates match your search.' : 'No candidates invited yet.'}
          </div>
        )}
      </div>
    </div>
  );
}

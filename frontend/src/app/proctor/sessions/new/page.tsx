// FILE: src/app/proctor/sessions/new/page.tsx
// Create session wizard

'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import apiClient from '@/lib/api';
import { Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';

export default function NewSessionPage() {
  const router = useRouter();
  const [title, setTitle] = useState('');
  const [type, setType] = useState<'exam' | 'interview'>('exam');
  const [scheduledAt, setScheduledAt] = useState('');
  const [durationMin, setDurationMin] = useState(60);
  const [description, setDescription] = useState('');
  const [loading, setLoading] = useState(false);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      const resp = await apiClient.post('/api/sessions', {
        title,
        type,
        scheduled_at: new Date(scheduledAt).toISOString(),
        duration_min: durationMin,
        description: description || undefined,
        settings: {},
      });

      toast.success('Session created!');
      router.push(`/proctor/sessions/${resp.data.id}`);
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to create session');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-white mb-6">Create New Session</h1>

      <form onSubmit={handleCreate} className="bg-gray-900 border border-gray-800 rounded-xl p-8 space-y-6">
        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">Session Title</label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="e.g., Final Exam — CS101"
            required
            className="w-full px-4 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-white
                       placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">Type</label>
          <div className="grid grid-cols-2 gap-3">
            {(['exam', 'interview'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setType(t)}
                className={`py-2.5 rounded-lg border text-sm font-medium capitalize transition-all
                  ${type === t ? 'bg-blue-600/20 border-blue-500 text-blue-400'
                              : 'bg-gray-800 border-gray-700 text-gray-400 hover:border-gray-600'}`}
              >
                {t}
              </button>
            ))}
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">Scheduled Date & Time</label>
          <input
            type="datetime-local"
            value={scheduledAt}
            onChange={(e) => setScheduledAt(e.target.value)}
            required
            className="w-full px-4 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-white
                       focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">
            Duration: {durationMin} minutes
          </label>
          <input
            type="range"
            min={10}
            max={480}
            step={5}
            value={durationMin}
            onChange={(e) => setDurationMin(Number(e.target.value))}
            className="w-full accent-blue-500"
          />
          <div className="flex justify-between text-xs text-gray-500 mt-1">
            <span>10 min</span>
            <span>8 hours</span>
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-300 mb-1.5">Description (optional)</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Instructions or notes for this session..."
            rows={3}
            className="w-full px-4 py-2.5 bg-gray-800 border border-gray-700 rounded-lg text-white
                       placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="w-full flex items-center justify-center gap-2 py-3 bg-blue-600 hover:bg-blue-700
                     disabled:bg-blue-800 text-white font-medium rounded-lg transition-colors"
        >
          {loading ? <><Loader2 className="w-4 h-4 animate-spin" /> Creating...</> : 'Create Session'}
        </button>
      </form>
    </div>
  );
}

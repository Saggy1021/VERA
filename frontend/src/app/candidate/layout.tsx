// FILE: src/app/candidate/layout.tsx
// Minimal layout, no nav

'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { Shield, LogOut } from 'lucide-react';

export default function CandidateLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();

  const handleLogout = async () => {
    await supabase.auth.signOut();
    router.push('/login');
  };

  useEffect(() => {
    const checkAuth = async () => {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) {
        router.push('/login');
        return;
      }
      const role = session.user.user_metadata?.role;
      if (role !== 'candidate') {
        router.push('/proctor/dashboard');
        return;
      }
    };
    checkAuth();
  }, [router]);

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col">
      {/* Minimal header — no sidebar for candidates */}
      <nav className="flex items-center justify-between px-6 py-3 bg-gray-900 border-b border-gray-800">
        <div className="flex items-center gap-3">
          <Shield className="w-5 h-5 text-blue-400" />
          <span className="text-lg font-bold text-white tracking-tight">SENTINEL</span>
          <span className="text-xs px-2 py-0.5 bg-emerald-600/20 text-emerald-400 rounded-full uppercase tracking-wider">
            Candidate
          </span>
        </div>
        <button
          onClick={handleLogout}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-gray-400 hover:text-white bg-gray-800 hover:bg-gray-700 rounded-lg transition-colors border border-gray-700"
        >
          <LogOut className="w-3.5 h-3.5" /> Logout
        </button>
      </nav>

      <main className="flex-1">
        <ErrorBoundary name="CandidateContent">
          {children}
        </ErrorBoundary>
      </main>
    </div>
  );
}

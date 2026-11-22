// FILE: src/app/proctor/layout.tsx
// Proctor sidebar + nav

'use client';

import { useEffect, useState } from 'react';
import { useRouter, usePathname } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { Navbar } from '@/components/shared/Navbar';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import {
  LayoutDashboard,
  MonitorPlay,
  Users,
  Shield,
} from 'lucide-react';
import Link from 'next/link';

const sidebarItems = [
  { href: '/proctor/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { href: '/proctor/sessions', label: 'Sessions', icon: MonitorPlay },
  { href: '/proctor/candidates', label: 'Candidates', icon: Users },
];

export default function ProctorLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [userName, setUserName] = useState('');

  useEffect(() => {
    const checkAuth = async () => {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) {
        router.push('/login');
        return;
      }
      const role = session.user.user_metadata?.role;
      if (role !== 'proctor') {
        router.push('/candidate/dashboard');
        return;
      }
      setUserName(session.user.user_metadata?.full_name || session.user.email || '');
    };
    checkAuth();
  }, [router]);

  return (
    <div className="min-h-screen bg-gray-950 flex flex-col">
      <ErrorBoundary name="ProctorNavbar">
        <Navbar role="proctor" userName={userName} />
      </ErrorBoundary>

      <div className="flex flex-1">
        {/* Sidebar */}
        <aside className="w-60 bg-gray-900 border-r border-gray-800 p-4 flex flex-col gap-1">
          {sidebarItems.map((item) => {
            const isActive = pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium
                           transition-colors
                  ${isActive
                    ? 'bg-blue-600/15 text-blue-400'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                  }`}
              >
                <Icon className="w-4 h-4" />
                {item.label}
              </Link>
            );
          })}
        </aside>

        {/* Main Content */}
        <main className="flex-1 p-6 overflow-auto">
          <ErrorBoundary name="ProctorContent">
            {children}
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

// FILE: src/components/shared/Navbar.tsx

'use client';

import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { LogOut, Shield } from 'lucide-react';

interface NavbarProps {
  role: 'proctor' | 'candidate';
  userName?: string;
}

export function Navbar({ role, userName }: NavbarProps) {
  const router = useRouter();

  const handleLogout = async () => {
    await supabase.auth.signOut();
    router.push('/login');
  };

  return (
    <nav className="flex items-center justify-between px-6 py-3 bg-gray-900 text-white border-b border-gray-800">
      <div className="flex items-center gap-3">
        <Shield className="w-6 h-6 text-blue-400" />
        <span className="text-lg font-bold tracking-tight">SENTINEL</span>
        <span className="text-xs px-2 py-0.5 bg-blue-600/20 text-blue-400 rounded-full uppercase tracking-wider">
          {role}
        </span>
      </div>

      <div className="flex items-center gap-4">
        {userName && (
          <span className="text-sm text-gray-400">{userName}</span>
        )}
        <button
          onClick={handleLogout}
          className="flex items-center gap-2 px-3 py-1.5 text-sm text-gray-400 hover:text-white
                     hover:bg-gray-800 rounded-md transition-colors"
        >
          <LogOut className="w-4 h-4" />
          Logout
        </button>
      </div>
    </nav>
  );
}

export default Navbar;

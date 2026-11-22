// FILE: src/app/page.tsx
// Landing: redirect by role

'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const checkAuth = async () => {
      const { data: { session } } = await supabase.auth.getSession();

      if (!session) {
        router.push('/login');
        return;
      }

      const role = session.user.user_metadata?.role as string;
      if (role === 'proctor') {
        router.push('/proctor/dashboard');
      } else if (role === 'candidate') {
        router.push('/candidate/dashboard');
      } else {
        router.push('/login');
      }
    };

    checkAuth();
  }, [router]);

  return (
    <div className="flex items-center justify-center min-h-screen">
      <LoadingSpinner size="lg" message="Redirecting..." />
    </div>
  );
}

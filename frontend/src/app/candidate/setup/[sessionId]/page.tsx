// FILE: src/app/candidate/setup/[sessionId]/page.tsx
// Pre-session wizard

'use client';

import { useParams } from 'next/navigation';
import { useRouter } from 'next/navigation';
import { useCallback } from 'react';
import { SetupWizard } from '@/components/candidate/SetupWizard';

export default function SetupPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;

  const handleComplete = useCallback(() => {
    router.push(`/candidate/session/${sessionId}`);
  }, [router, sessionId]);

  return (
    <div className="min-h-screen bg-gray-950 py-10">
      <SetupWizard sessionId={sessionId} onComplete={handleComplete} />
    </div>
  );
}

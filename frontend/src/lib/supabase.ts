// FILE: src/lib/supabase.ts
// Supabase browser client — uses @supabase/ssr (required for Next.js 14+/15+)
// SECURITY: Only NEXT_PUBLIC_ vars reach the browser.
// SUPABASE_SERVICE_ROLE_KEY is NEVER referenced here — it lives only in backend/config.py.

import { createBrowserClient } from '@supabase/ssr';

export const supabase = createBrowserClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
);

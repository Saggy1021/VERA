// FILE: src/middleware.ts
// Next.js middleware: role-based route guard using @supabase/ssr

import { createServerClient } from '@supabase/ssr';
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export async function middleware(req: NextRequest) {
  let res = NextResponse.next({
    request: {
      headers: req.headers,
    },
  });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return req.cookies.getAll();
        },
        setAll(cookiesToSet: Array<{ name: string; value: string; options?: any }>) {
          cookiesToSet.forEach(({ name, value }) => req.cookies.set(name, value));
          res = NextResponse.next({
            request: {
              headers: req.headers,
            },
          });
          cookiesToSet.forEach(({ name, value, options }) =>
            res.cookies.set(name, value, options)
          );
        },
      },
    }
  );

  const { data: { session } } = await supabase.auth.getSession();
  const path = req.nextUrl.pathname;

  // Redirect to login if not authenticated
  if (!session && !path.startsWith('/login') && !path.startsWith('/register')) {
    return NextResponse.redirect(new URL('/login', req.url));
  }

  if (session) {
    const role = session.user.user_metadata?.role as string;
    // Proctor trying to access candidate routes → redirect to proctor dashboard
    if (path.startsWith('/candidate') && role !== 'candidate') {
      return NextResponse.redirect(new URL('/proctor/dashboard', req.url));
    }
    // Candidate trying to access proctor routes → redirect to candidate dashboard
    if (path.startsWith('/proctor') && role !== 'proctor') {
      return NextResponse.redirect(new URL('/candidate/dashboard', req.url));
    }
  }

  return res;
}

export const config = {
  matcher: ['/proctor/:path*', '/candidate/:path*'],
};

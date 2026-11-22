# FILE: backend/db/bootstrap.py
"""
Idempotent Supabase & Environment Bootstrap script for SENTINEL / VERA.
- Applies schema migrations safely (enums, tables, unique constraints, indexes).
- Adds auth.users -> public.profiles trigger.
- Creates sentinel-evidence storage bucket.
- Seeds Proctor and Candidate demo accounts + demo exam session.
"""

import os
import sys
import asyncio
import ssl
from dotenv import load_dotenv

# Load env from root or backend
load_dotenv(".env")
load_dotenv("backend/.env")

import asyncpg
from supabase import create_client, Client

DATABASE_URL = os.getenv("DATABASE_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
STORAGE_BUCKET = os.getenv("SUPABASE_STORAGE_BUCKET", "sentinel-evidence")

PROCTOR_EMAIL = "proctor@vera.demo"
PROCTOR_PASSWORD = "VeraProctor2026!"
CANDIDATE_EMAIL = "candidate@vera.demo"
CANDIDATE_PASSWORD = "VeraCandidate2026!"
DEMO_SESSION_ID = "d3b07384-d113-4f44-93c0-3051187d7b3e"


SCHEMA_SQL = """
-- ── 1. ENUMS (Safe creation) ──────────────────────────
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'user_role') THEN
    CREATE TYPE user_role AS ENUM ('proctor', 'candidate');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'session_status') THEN
    CREATE TYPE session_status AS ENUM ('scheduled','active','completed','cancelled');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'session_type') THEN
    CREATE TYPE session_type AS ENUM ('exam','interview');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_severity') THEN
    CREATE TYPE event_severity AS ENUM ('low','medium','high','critical');
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'event_type') THEN
    CREATE TYPE event_type AS ENUM (
      'no_face','multiple_faces','head_turned','gaze_away',
      'tab_switch','fullscreen_exit','object_detected',
      'audio_activity','second_speaker','identity_mismatch',
      'copy_paste','context_switch','session_end'
    );
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'report_status') THEN
    CREATE TYPE report_status AS ENUM ('draft','published','suppressed');
  END IF;
END $$;

-- ── 2. TABLES ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.profiles (
  id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  role        user_role NOT NULL DEFAULT 'candidate',
  full_name   TEXT NOT NULL,
  email       TEXT NOT NULL UNIQUE,
  institution TEXT,
  avatar_url  TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.sessions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  proctor_id   UUID NOT NULL REFERENCES public.profiles(id),
  title        TEXT NOT NULL,
  description  TEXT,
  type         session_type NOT NULL DEFAULT 'exam',
  status       session_status NOT NULL DEFAULT 'scheduled',
  scheduled_at TIMESTAMPTZ NOT NULL,
  duration_min INTEGER NOT NULL DEFAULT 60,
  started_at   TIMESTAMPTZ,
  ended_at     TIMESTAMPTZ,
  settings     JSONB DEFAULT '{}',
  created_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.session_candidates (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      UUID NOT NULL REFERENCES public.sessions(id) ON DELETE CASCADE,
  candidate_id    UUID NOT NULL REFERENCES public.profiles(id),
  invite_token    TEXT UNIQUE DEFAULT encode(gen_random_bytes(32),'hex'),
  enrolled_at     TIMESTAMPTZ,
  face_descriptor JSONB,
  joined_at       TIMESTAMPTZ,
  left_at         TIMESTAMPTZ,
  UNIQUE(session_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS public.malpractice_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      UUID NOT NULL REFERENCES public.sessions(id) ON DELETE CASCADE,
  candidate_id    UUID NOT NULL REFERENCES public.profiles(id),
  event_type      event_type NOT NULL,
  severity        event_severity NOT NULL,
  risk_score      SMALLINT NOT NULL DEFAULT 0,
  description     TEXT,
  metadata        JSONB DEFAULT '{}',
  screenshot_url  TEXT,
  gemini_verdict  TEXT,
  occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.reports (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      UUID NOT NULL REFERENCES public.sessions(id),
  candidate_id    UUID NOT NULL REFERENCES public.profiles(id),
  status          report_status NOT NULL DEFAULT 'draft',
  overall_score   SMALLINT,
  summary         TEXT,
  event_count     JSONB DEFAULT '{}',
  timeline        JSONB DEFAULT '[]',
  published_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.audit_log (
  id          BIGSERIAL PRIMARY KEY,
  actor_id    UUID REFERENCES auth.users(id),
  actor_role  user_role,
  action      TEXT NOT NULL,
  resource    TEXT,
  resource_id UUID,
  ip_address  INET,
  user_agent  TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- Ensure UNIQUE(session_id, candidate_id) on reports
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'reports_session_id_candidate_id_key'
  ) THEN
    ALTER TABLE public.reports ADD CONSTRAINT reports_session_id_candidate_id_key UNIQUE (session_id, candidate_id);
  END IF;
EXCEPTION
  WHEN others THEN NULL;
END $$;

-- ── 3. INDEXES ─────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_events_clip_url
  ON public.malpractice_events ((metadata->>'clip_url'))
  WHERE metadata->>'clip_url' IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_events_session_severity_time
  ON public.malpractice_events (session_id, severity, occurred_at DESC);

-- ── 4. AUTH TRIGGER ────────────────────────────────────
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, role, full_name, email)
  VALUES (
    new.id,
    COALESCE((new.raw_user_meta_data->>'role')::public.user_role, 'candidate'::public.user_role),
    COALESCE(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)),
    new.email
  )
  ON CONFLICT (id) DO UPDATE
  SET full_name = EXCLUDED.full_name,
      email = EXCLUDED.email;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- Enable RLS
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.session_candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.malpractice_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;

-- Base RLS policies if not exists
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'profiles_allow_all') THEN
    CREATE POLICY profiles_allow_all ON public.profiles FOR ALL USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'sessions_allow_all') THEN
    CREATE POLICY sessions_allow_all ON public.sessions FOR ALL USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'candidates_allow_all') THEN
    CREATE POLICY candidates_allow_all ON public.session_candidates FOR ALL USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'events_allow_all') THEN
    CREATE POLICY events_allow_all ON public.malpractice_events FOR ALL USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'reports_allow_all') THEN
    CREATE POLICY reports_allow_all ON public.reports FOR ALL USING (true);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE policyname = 'audit_allow_all') THEN
    CREATE POLICY audit_allow_all ON public.audit_log FOR ALL USING (true);
  END IF;
END $$;
"""


async def main():
    print("[1/4] Connecting to Database...")
    if not DATABASE_URL:
        print("ERROR: DATABASE_URL not set in environment.")
        sys.exit(1)

    # Clean connection string
    conn = await asyncpg.connect(dsn=DATABASE_URL, ssl="require")
    print("Database connected successfully.")

    print("[2/4] Applying idempotent schema migrations & triggers...")
    await conn.execute(SCHEMA_SQL)
    print("Schema & triggers applied successfully.")

    print("[3/4] Initializing Supabase Admin & Storage bucket...")
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    
    # Bucket check / creation
    try:
        buckets = supabase.storage.list_buckets()
        bucket_names = [b.name for b in buckets]
        if STORAGE_BUCKET not in bucket_names:
            print(f"Creating storage bucket: {STORAGE_BUCKET}")
            supabase.storage.create_bucket(STORAGE_BUCKET, options={"public": True})
        else:
            print(f"Storage bucket '{STORAGE_BUCKET}' already exists.")
    except Exception as e:
        print(f"Bucket check/create notice: {e}")

    print("[4/4] Seeding Proctor & Candidate demo accounts...")
    
    # 1. Proctor User
    proctor_id = None
    try:
        res = supabase.auth.admin.create_user({
            "email": PROCTOR_EMAIL,
            "password": PROCTOR_PASSWORD,
            "email_confirm": True,
            "user_metadata": {"role": "proctor", "full_name": "Dr. Sarah Connor (Chief Proctor)"}
        })
        proctor_id = res.user.id
        print(f"Created Proctor auth user: {PROCTOR_EMAIL} (ID: {proctor_id})")
    except Exception as e:
        print(f"Proctor auth user notice: {e}")
        # Fetch existing
        users = supabase.auth.admin.list_users()
        for u in users:
            if u.email == PROCTOR_EMAIL:
                proctor_id = u.id
                break

    # 2. Candidate User
    candidate_id = None
    try:
        res = supabase.auth.admin.create_user({
            "email": CANDIDATE_EMAIL,
            "password": CANDIDATE_PASSWORD,
            "email_confirm": True,
            "user_metadata": {"role": "candidate", "full_name": "Alex Mercer (Candidate)"}
        })
        candidate_id = res.user.id
        print(f"Created Candidate auth user: {CANDIDATE_EMAIL} (ID: {candidate_id})")
    except Exception as e:
        print(f"Candidate auth user notice: {e}")
        users = supabase.auth.admin.list_users()
        for u in users:
            if u.email == CANDIDATE_EMAIL:
                candidate_id = u.id
                break

    # Upsert profiles in DB directly
    if proctor_id:
        await conn.execute("""
            INSERT INTO public.profiles (id, role, full_name, email, institution)
            VALUES ($1, 'proctor', 'Dr. Sarah Connor', $2, 'MIT - Department of Computing')
            ON CONFLICT (id) DO UPDATE
            SET role = 'proctor', full_name = EXCLUDED.full_name, email = EXCLUDED.email;
        """, proctor_id, PROCTOR_EMAIL)

    if candidate_id:
        await conn.execute("""
            INSERT INTO public.profiles (id, role, full_name, email, institution)
            VALUES ($1, 'candidate', 'Alex Mercer', $2, 'MIT Candidate')
            ON CONFLICT (id) DO UPDATE
            SET role = 'candidate', full_name = EXCLUDED.full_name, email = EXCLUDED.email;
        """, candidate_id, CANDIDATE_EMAIL)

    # Seed Demo Session
    if proctor_id and candidate_id:
        print("Seeding active demo session...")
        await conn.execute("""
            INSERT INTO public.sessions (id, proctor_id, title, description, type, status, scheduled_at, duration_min, settings)
            VALUES ($1, $2, 'CS 401: Advanced AI & Neural Systems Final Exam', 
                    'Comprehensive 60-minute proctored examination covering edge ML architectures, real-time computer vision, and distributed inference.',
                    'exam', 'active', NOW() - INTERVAL '5 minutes', 60, 
                    '{"identity_threshold": 0.6, "exam_url": "https://example.com/exam"}'::jsonb)
            ON CONFLICT (id) DO UPDATE
            SET status = 'active', proctor_id = EXCLUDED.proctor_id, title = EXCLUDED.title;
        """, DEMO_SESSION_ID, proctor_id)

        # Invite Candidate
        await conn.execute("""
            INSERT INTO public.session_candidates (session_id, candidate_id, enrolled_at, joined_at)
            VALUES ($1, $2, NOW(), NOW())
            ON CONFLICT (session_id, candidate_id) DO UPDATE
            SET enrolled_at = NOW(), joined_at = NOW();
        """, DEMO_SESSION_ID, candidate_id)

    await conn.close()
    print("\n=======================================================")
    print("SUCCESS: Database bootstrapped & Demo Accounts Seeded!")
    print(f"Proctor:   {PROCTOR_EMAIL}  |  Password: {PROCTOR_PASSWORD}")
    print(f"Candidate: {CANDIDATE_EMAIL} |  Password: {CANDIDATE_PASSWORD}")
    print(f"Demo Session ID: {DEMO_SESSION_ID}")
    print("=======================================================\n")


if __name__ == "__main__":
    asyncio.run(main())

-- FILE: backend/db/migrations/001_initial.sql
-- Run this in Supabase SQL Editor or via psql

-- ── ENUMS ────────────────────────────────────
CREATE TYPE user_role AS ENUM ('proctor', 'candidate');
CREATE TYPE session_status AS ENUM ('scheduled','active','completed','cancelled');
CREATE TYPE session_type AS ENUM ('exam','interview');
CREATE TYPE event_severity AS ENUM ('low','medium','high','critical');
CREATE TYPE event_type AS ENUM (
  'no_face','multiple_faces','head_turned','gaze_away',
  'tab_switch','fullscreen_exit','object_detected',
  'audio_activity','second_speaker','identity_mismatch',
  'copy_paste','context_switch','session_end'
);
CREATE TYPE report_status AS ENUM ('draft','published','suppressed');

-- ── PROFILES (extends Supabase auth.users) ───
CREATE TABLE public.profiles (
  id          UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  role        user_role NOT NULL,
  full_name   TEXT NOT NULL,
  email       TEXT NOT NULL UNIQUE,
  institution TEXT,
  avatar_url  TEXT,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE public.profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "own profile" ON public.profiles
  FOR ALL USING (auth.uid() = id);
CREATE POLICY "proctor sees candidates in their sessions"
  ON public.profiles FOR SELECT
  USING (role = 'candidate' AND EXISTS (
    SELECT 1 FROM public.session_candidates sc
    JOIN public.sessions s ON s.id = sc.session_id
    WHERE sc.candidate_id = public.profiles.id
    AND s.proctor_id = auth.uid()
  ));

-- ── SESSIONS ──────────────────────────────────
CREATE TABLE public.sessions (
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
ALTER TABLE public.sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "proctor manages own sessions"
  ON public.sessions FOR ALL
  USING (proctor_id = auth.uid());
CREATE POLICY "candidate sees their sessions"
  ON public.sessions FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM public.session_candidates
    WHERE session_id = public.sessions.id
    AND candidate_id = auth.uid()
  ));

-- ── SESSION_CANDIDATES (join table) ──────────
CREATE TABLE public.session_candidates (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      UUID NOT NULL REFERENCES public.sessions(id) ON DELETE CASCADE,
  candidate_id    UUID NOT NULL REFERENCES public.profiles(id),
  invite_token    TEXT UNIQUE DEFAULT encode(gen_random_bytes(32),'hex'),
  enrolled_at     TIMESTAMPTZ,
  face_descriptor JSONB,   -- 128-dim array from face-api.js enrollment
  joined_at       TIMESTAMPTZ,
  left_at         TIMESTAMPTZ,
  UNIQUE(session_id, candidate_id)
);
ALTER TABLE public.session_candidates ENABLE ROW LEVEL SECURITY;
CREATE POLICY "proctor manages candidates in own sessions"
  ON public.session_candidates FOR ALL
  USING (EXISTS (
    SELECT 1 FROM public.sessions s
    WHERE s.id = session_id AND s.proctor_id = auth.uid()
  ));
CREATE POLICY "candidate sees own row"
  ON public.session_candidates FOR SELECT
  USING (candidate_id = auth.uid());

-- ── MALPRACTICE_EVENTS ────────────────────────
CREATE TABLE public.malpractice_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      UUID NOT NULL REFERENCES public.sessions(id) ON DELETE CASCADE,
  candidate_id    UUID NOT NULL REFERENCES public.profiles(id),
  event_type      event_type NOT NULL,
  severity        event_severity NOT NULL,
  risk_score      SMALLINT NOT NULL DEFAULT 0,  -- 0-100
  description     TEXT,
  metadata        JSONB DEFAULT '{}',
  screenshot_url  TEXT,
  gemini_verdict  TEXT,   -- AI second opinion text
  occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
ALTER TABLE public.malpractice_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "proctor sees events in own sessions"
  ON public.malpractice_events FOR SELECT
  USING (EXISTS (
    SELECT 1 FROM public.sessions s
    WHERE s.id = session_id AND s.proctor_id = auth.uid()
  ));
CREATE POLICY "only backend service role inserts events"
  ON public.malpractice_events FOR INSERT
  WITH CHECK (auth.role() = 'service_role');

-- ── REPORTS ───────────────────────────────────
CREATE TABLE public.reports (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id      UUID NOT NULL REFERENCES public.sessions(id),
  candidate_id    UUID NOT NULL REFERENCES public.profiles(id),
  status          report_status NOT NULL DEFAULT 'draft',
  overall_score   SMALLINT,    -- 0-100 integrity score (100 = clean)
  summary         TEXT,
  event_count     JSONB DEFAULT '{}',  -- {low:3, medium:1, high:0, critical:0}
  timeline        JSONB DEFAULT '[]',  -- array of event summaries
  published_at    TIMESTAMPTZ,
  created_at      TIMESTAMPTZ DEFAULT NOW()
);
ALTER TABLE public.reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY "proctor manages own session reports"
  ON public.reports FOR ALL
  USING (EXISTS (
    SELECT 1 FROM public.sessions s
    WHERE s.id = session_id AND s.proctor_id = auth.uid()
  ));
CREATE POLICY "candidate sees published report"
  ON public.reports FOR SELECT
  USING (candidate_id = auth.uid() AND status = 'published');

-- ── AUDIT_LOG (append-only) ───────────────────
CREATE TABLE public.audit_log (
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
ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;
CREATE POLICY "proctors read audit for own sessions"
  ON public.audit_log FOR SELECT
  USING (actor_role = 'proctor' AND actor_id = auth.uid());
-- No UPDATE or DELETE policies — audit log is append-only

-- FILE: backend/db/migrations/003_clip_url_index.sql
-- A2: Index on metadata->>'clip_url' for fast proctor evidence gallery queries.
-- Without this, fetching all events WITH clips requires a full table scan on
-- malpractice_events filtering metadata JSONB — slow at scale.
--
-- The WHERE clause makes this a partial index: only rows that HAVE a clip_url
-- are indexed. This keeps the index small (only ~5-10% of events have clips).
-- Proctor gallery query: SELECT * FROM malpractice_events WHERE metadata->>'clip_url' IS NOT NULL
-- will use this index automatically.

CREATE INDEX IF NOT EXISTS idx_events_clip_url
  ON public.malpractice_events ((metadata->>'clip_url'))
  WHERE metadata->>'clip_url' IS NOT NULL;

-- Also add index for the common proctor query pattern: events by session + severity
-- (used in get_recent_high_events and the C1 missed-events reconnect query)
CREATE INDEX IF NOT EXISTS idx_events_session_severity_time
  ON public.malpractice_events (session_id, severity, occurred_at DESC);

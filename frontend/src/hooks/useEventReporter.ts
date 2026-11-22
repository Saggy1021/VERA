// FILE: src/hooks/useEventReporter.ts
// Batched event POST to backend

'use client';

import { useRef, useCallback } from 'react';
import apiClient from '@/lib/api';
import { supabase } from '@/lib/supabase';

export interface MalpracticeEvent {
  sessionId: string;
  event_type: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  risk_score: number;
  description?: string;
  metadata?: Record<string, any>;
  screenshot_url?: string;
  occurred_at?: string;
}

export function useEventReporter(sessionId: string) {
  const eventBuffer = useRef<MalpracticeEvent[]>([]);
  const flushIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const addEvent = useCallback((event: Omit<MalpracticeEvent, 'sessionId'>) => {
    eventBuffer.current.push({
      ...event,
      sessionId,
      occurred_at: event.occurred_at || new Date().toISOString(),
    });
  }, [sessionId]);

  const flushEvents = useCallback(async () => {
    if (eventBuffer.current.length === 0) return;

    const events = [...eventBuffer.current];
    eventBuffer.current = [];

    try {
      await apiClient.post('/api/events/batch', {
        events: events.map((e) => ({
          session_id: e.sessionId,
          event_type: e.event_type,
          severity: e.severity,
          risk_score: e.risk_score,
          description: e.description,
          metadata: e.metadata || {},
          screenshot_url: e.screenshot_url,
          occurred_at: e.occurred_at,
        })),
      });
    } catch (err) {
      // Re-add failed events back to buffer for retry
      eventBuffer.current = [...events, ...eventBuffer.current];
      console.error('[useEventReporter] Failed to flush events:', err);
    }
  }, []);

  const sendHighEvent = useCallback(async (
    event: Omit<MalpracticeEvent, 'sessionId'>,
    screenshot: string, // base64 JPEG
  ) => {
    try {
      const resp = await apiClient.post('/api/events/high', {
        session_id: sessionId,
        event_type: event.event_type,
        severity: event.severity || 'high',
        risk_score: event.risk_score,
        description: event.description,
        metadata: event.metadata || {},
        screenshot,
        occurred_at: event.occurred_at || new Date().toISOString(),
      });
      return resp.data;
    } catch (err) {
      console.error('[useEventReporter] Failed to send high event:', err);
      return null;
    }
  }, [sessionId]);

  // Upload a 30-second WebM clip Blob to Supabase Storage via backend.
  // Returns the clip URL on success, undefined on failure (non-blocking).
  const uploadClip = useCallback(async (
    blob: Blob,
    currentSessionId: string,
    eventType: string,
  ): Promise<string | undefined> => {
    try {
      const formData = new FormData();
      const filename = `${currentSessionId}_${eventType}_${Date.now()}.webm`;
      formData.append('file', blob, filename);
      formData.append('session_id', currentSessionId);
      formData.append('event_type', eventType);

      const resp = await apiClient.post('/api/events/clip', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
        timeout: 15000, // 15s timeout — clip is ~500KB-2MB
      });
      return resp.data?.clip_url as string | undefined;
    } catch (err) {
      console.warn('[useEventReporter] Clip upload failed (non-fatal):', err);
      return undefined;
    }
  }, []);

  const startAutoFlush = useCallback(() => {
    if (flushIntervalRef.current) return;
    // Batch events, POST to backend every 10s
    flushIntervalRef.current = setInterval(flushEvents, 10000);
  }, [flushEvents]);

  const stopAutoFlush = useCallback(() => {
    if (flushIntervalRef.current) {
      clearInterval(flushIntervalRef.current);
      flushIntervalRef.current = null;
    }
    // B4: Use navigator.sendBeacon for the final flush.
    // sendBeacon is specifically designed for data delivery on page close/navigation.
    // It is non-blocking and browsers guarantee delivery even during unload.
    const pendingEvents = eventBuffer.current;
    if (pendingEvents.length === 0) return;
    eventBuffer.current = [];

    const payload = JSON.stringify({
      events: pendingEvents.map((e) => ({
        session_id: e.sessionId,
        event_type: e.event_type,
        severity: e.severity,
        risk_score: e.risk_score,
        description: e.description,
        metadata: e.metadata || {},
        screenshot_url: e.screenshot_url,
        occurred_at: e.occurred_at,
      })),
    });

    const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || '';
    supabase.auth.getSession().then(({ data }: any) => {
      const token = data?.session?.access_token || '';
      fetch(`${backendUrl}/api/events/batch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: payload,
        keepalive: true,
      }).catch((err) => {
        console.warn('[useEventReporter] Final flush keepalive fetch failed:', err);
      });
    });
  }, [flushEvents]);

  return { addEvent, flushEvents, sendHighEvent, uploadClip, startAutoFlush, stopAutoFlush };
}


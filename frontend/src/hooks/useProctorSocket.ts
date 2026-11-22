// FILE: src/hooks/useProctorSocket.ts
// Proctor Socket.io listener

'use client';

import { useRef, useCallback, useEffect, useState } from 'react';
import { io, type Socket } from 'socket.io-client';
import { useProctorStore } from '@/store/proctorStore';
import { supabase } from '@/lib/supabase';

export function useProctorSocket(sessionId: string | null) {
  const socketRef = useRef<Socket | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const { updateCandidate, addAlert } = useProctorStore();

  const connect = useCallback(async () => {
    if (!sessionId) return;
    if (socketRef.current?.connected) return;

    let { data: { session } } = await supabase.auth.getSession();
    if (!session) {
      // Token may be expired — attempt a silent refresh once
      const { data: refreshed } = await supabase.auth.refreshSession();
      session = refreshed.session;
    }
    if (!session) return;

    const socketUrl = process.env.NEXT_PUBLIC_SOCKET_URL || 'http://localhost:8000';

    const socket = io(socketUrl, {
      transports: ['websocket', 'polling'],
      autoConnect: true,
    });

    socket.on('connect', () => {
      setIsConnected(true);
      // Join the proctor room for this session.
      // C1: The backend will respond with 'missed_events' containing any
      // HIGH/CRITICAL alerts from the last 30 minutes that arrived during disconnect.
      socket.emit('join_proctor_room', {
        sessionId,
        token: session.access_token,
      });
    });

    socket.on('reconnect', () => {
      // C1: Re-join on reconnect so missed-events backfill fires every time
      socket.emit('join_proctor_room', {
        sessionId,
        token: session.access_token,
      });
    });

    socket.on('disconnect', () => {
      setIsConnected(false);
    });

    socket.on('joined', (data: any) => {
      console.log('[ProctorSocket] Joined room:', data.room);
    });

    // C1: Backfill missed HIGH/CRITICAL events after reconnect
    socket.on('missed_events', (data: any) => {
      const { events, count } = data;
      console.log(`[ProctorSocket] Backfilling ${count} missed events`);
      for (const event of events) {
        addAlert({
          id: event.id || `missed_${Date.now()}_${Math.random()}`,
          candidateId: event.candidate_id,
          candidateName: '',
          eventType: event.event_type,
          severity: event.severity,
          timestamp: event.occurred_at || new Date().toISOString(),
          thumbnailUrl: event.screenshot_url || null,
          geminiVerdict: event.gemini_verdict || null,
        });
      }
    });

    socket.on('candidate_event', (data: any) => {
      const { candidateId, event } = data;

      // Update candidate risk level
      updateCandidate(candidateId, {
        riskLevel: event.risk_score || 0,
        lastEvent: event.event_type,
        lastEventTime: event.occurred_at,
      });

      // Add to alert feed
      addAlert({
        id: event.id || `${Date.now()}`,
        candidateId,
        candidateName: '', // Will be enriched by the store
        eventType: event.event_type,
        severity: event.severity,
        timestamp: event.occurred_at || new Date().toISOString(),
        thumbnailUrl: event.screenshot_url || null,
        geminiVerdict: event.gemini_verdict || null,
      });
    });

    socket.on('candidate_status', (data: any) => {
      const { candidateId, status, riskLevel, thumbnailUrl } = data;
      updateCandidate(candidateId, {
        status,
        ...(riskLevel !== undefined ? { riskLevel } : {}),
        ...(thumbnailUrl ? { thumbnailUrl } : {}),
      });
    });

    socket.on('session_alert', (data: any) => {
      console.log('[ProctorSocket] Session alert:', data);
    });

    socket.on('error', (data: any) => {
      console.error('[ProctorSocket] Error:', data);
    });

    socketRef.current = socket;
  }, [sessionId, updateCandidate, addAlert]);

  const disconnect = useCallback(() => {
    if (socketRef.current) {
      socketRef.current.disconnect();
      socketRef.current = null;
      setIsConnected(false);
    }
  }, []);

  const sendWarning = useCallback(async (candidateId: string, message: string) => {
    if (socketRef.current && sessionId) {
      const { data: { session } } = await supabase.auth.getSession();
      socketRef.current.emit('send_warning', {
        sessionId,
        candidateId,
        message,
        token: session?.access_token,
      });
    }
  }, [sessionId]);

  useEffect(() => {
    return () => { disconnect(); };
  }, [disconnect]);

  return { connect, disconnect, sendWarning, isConnected };
}

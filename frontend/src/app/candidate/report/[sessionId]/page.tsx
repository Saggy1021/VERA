// FILE: src/app/candidate/report/[sessionId]/page.tsx
// Candidate-facing report — HTML summary view ONLY.
//
// SECURITY CONTRACT:
// - No evidence screenshots shown to candidate (proctor-only)
// - No Gemini verdicts shown (proctor-only)
// - No jsPDF download (proctor-only)
// - Only: integrity score, event type counts, event timeline (type + severity + time)
// - Timeline descriptions are shown because they are the candidate's own actions.

'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import apiClient from '@/lib/api';
import { supabase } from '@/lib/supabase';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { FileText, CheckCircle2, AlertTriangle, Info, Shield } from 'lucide-react';
import { getRiskColor } from '@/lib/utils';

// Candidate-safe view of the report — no screenshots, no AI verdicts
interface CandidateReportView {
  overall_score: number;
  summary: string;
  status: string;
  event_count: Record<string, number>;
  // Timeline contains ONLY: time, type, severity — no screenshot_url, no gemini_verdict
  timeline: Array<{
    time: string;
    type: string;
    severity: string;
    description: string;
  }>;
  created_at: string;
}

export default function CandidateReportPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const [report, setReport] = useState<CandidateReportView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchReport = async () => {
      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) return;

        const resp = await apiClient.get(
          `/api/reports/${sessionId}/${session.user.id}`
        );

        const raw = resp.data;

        // Strip proctor-only fields before rendering.
        // Even if the backend ever mistakenly sends them,
        // they will never render in this component.
        const safeView: CandidateReportView = {
          overall_score: raw.overall_score,
          summary: raw.summary,
          status: raw.status,
          event_count: raw.event_count || {},
          timeline: (raw.timeline || []).map((evt: any) => ({
            time: evt.time || evt.occurred_at,
            type: evt.type || evt.event_type,
            severity: evt.severity,
            description: evt.description,
            // screenshot_url: STRIPPED
            // gemini_verdict: STRIPPED
            // clip_url: STRIPPED
          })),
          created_at: raw.created_at,
        };

        setReport(safeView);
      } catch (err: any) {
        setError(err?.response?.data?.detail || 'Report not available');
      } finally {
        setLoading(false);
      }
    };
    fetchReport();
  }, [sessionId]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" message="Loading report..." />
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-gray-400">
        <FileText className="w-12 h-12 mb-4 opacity-50" />
        <p className="text-lg font-medium">{error || 'Report not available'}</p>
        <p className="text-sm mt-1">The proctor has not published your report yet.</p>
      </div>
    );
  }

  const integrityColor = getRiskColor(100 - report.overall_score);

  return (
    <div className="max-w-2xl mx-auto p-6">
      <ErrorBoundary name="CandidateReport">
        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <Shield className="w-6 h-6 text-blue-400" />
          <div>
            <h1 className="text-2xl font-bold text-white">Session Report</h1>
            <p className="text-gray-400 text-sm">
              Generated {new Date(report.created_at).toLocaleDateString()}
            </p>
          </div>
        </div>

        {/* Integrity Score Card */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 mb-6 text-center">
          <div
            className="text-7xl font-black mb-2"
            style={{ color: integrityColor }}
          >
            {report.overall_score}
          </div>
          <div className="text-gray-400 text-sm mb-4">Integrity Score (out of 100)</div>

          {report.overall_score >= 80 ? (
            <div className="flex items-center justify-center gap-2 text-green-400 text-sm">
              <CheckCircle2 className="w-4 h-4" />
              No significant integrity issues detected
            </div>
          ) : report.overall_score >= 50 ? (
            <div className="flex items-center justify-center gap-2 text-yellow-400 text-sm">
              <AlertTriangle className="w-4 h-4" />
              Some integrity flags were detected during this session
            </div>
          ) : (
            <div className="flex items-center justify-center gap-2 text-red-400 text-sm">
              <AlertTriangle className="w-4 h-4" />
              Multiple integrity concerns were flagged in this session
            </div>
          )}
        </div>

        {/* Summary */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
          <h3 className="text-sm font-semibold text-gray-300 mb-3 flex items-center gap-2">
            <Info className="w-4 h-4" />
            Summary
          </h3>
          <p className="text-gray-400 text-sm leading-relaxed">{report.summary}</p>
        </div>

        {/* Event Counts by Severity */}
        <div className="grid grid-cols-4 gap-3 mb-6">
          {(['critical', 'high', 'medium', 'low'] as const).map((severity) => (
            <div
              key={severity}
              className="bg-gray-900 border border-gray-800 rounded-xl p-4 text-center"
            >
              <div className={`text-2xl font-bold ${
                severity === 'critical' ? 'text-red-500' :
                severity === 'high' ? 'text-orange-500' :
                severity === 'medium' ? 'text-yellow-500' :
                'text-green-500'
              }`}>
                {report.event_count[severity] || 0}
              </div>
              <div className="text-xs text-gray-500 capitalize mt-1">{severity}</div>
            </div>
          ))}
        </div>

        {/* Timeline — type, severity, time, description ONLY */}
        {report.timeline.length > 0 && (
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-semibold text-gray-300 mb-4">Event Log</h3>
            <div className="space-y-2 max-h-80 overflow-y-auto">
              {report.timeline.map((event, i) => (
                <div key={i} className="flex items-start gap-3 text-xs py-1.5 border-b border-gray-800/60 last:border-0">
                  <span className="text-gray-600 font-mono min-w-[72px] flex-shrink-0">
                    {event.time ? new Date(event.time).toLocaleTimeString() : '--'}
                  </span>
                  <span className={`px-1.5 py-0.5 rounded text-[10px] font-medium flex-shrink-0 ${
                    event.severity === 'critical' ? 'bg-red-600/20 text-red-400' :
                    event.severity === 'high' ? 'bg-orange-500/20 text-orange-400' :
                    event.severity === 'medium' ? 'bg-yellow-600/20 text-yellow-400' :
                    'bg-gray-600/20 text-gray-400'
                  }`}>
                    {(event.type || '').replace(/_/g, ' ')}
                  </span>
                  <span className="text-gray-400 leading-relaxed">{event.description}</span>
                  {/* screenshot_url, gemini_verdict, clip_url are intentionally NOT rendered */}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Explanation note */}
        <div className="mt-6 p-4 bg-blue-500/5 border border-blue-500/20 rounded-lg text-xs text-blue-300 leading-relaxed">
          <strong>About this report:</strong> This is a summary of your session integrity score.
          Detailed evidence and AI analysis are available to your proctor only.
          If you believe any flags are erroneous, please contact your proctor directly.
        </div>
      </ErrorBoundary>
    </div>
  );
}

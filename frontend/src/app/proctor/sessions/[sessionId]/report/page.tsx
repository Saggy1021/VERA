// FILE: src/app/proctor/sessions/[sessionId]/report/page.tsx
// Proctor: view/publish/suppress reports for a session

'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams } from 'next/navigation';
import apiClient from '@/lib/api';
import { LoadingSpinner } from '@/components/shared/LoadingSpinner';
import { ErrorBoundary } from '@/components/shared/ErrorBoundary';
import { getRiskColor } from '@/lib/utils';
import { FileText, Send, EyeOff, Download, CheckCircle2, AlertTriangle } from 'lucide-react';
import toast from 'react-hot-toast';
import jsPDF from 'jspdf';

interface CandidateReport {
  candidate_id: string;
  candidate_name: string;
  candidate_email: string;
  report: {
    id: string;
    overall_score: number;
    summary: string;
    status: string;
    event_count: Record<string, number>;
    timeline: Array<{
      time: string;
      type: string;
      severity: string;
      description: string;
      risk_score: number;
    }>;
    created_at: string;
    published_at: string | null;
  } | null;
}

export default function ProctorReportPage() {
  const params = useParams();
  const sessionId = params.sessionId as string;
  const [reports, setReports] = useState<CandidateReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [sessionTitle, setSessionTitle] = useState('');

  useEffect(() => {
    const fetchData = async () => {
      try {
        // Fetch session details
        const sessionResp = await apiClient.get(`/api/sessions/${sessionId}`);
        setSessionTitle(sessionResp.data.title);

        // Fetch candidates
        const candidatesResp = await apiClient.get(`/api/sessions/${sessionId}/candidates`);
        const candidates = candidatesResp.data;

        // Fetch report for each candidate
        const reportsList: CandidateReport[] = [];
        for (const c of candidates) {
          let report = null;
          try {
            const reportResp = await apiClient.get(
              `/api/reports/${sessionId}/${c.candidate_id}`
            );
            report = reportResp.data;
          } catch {
            // No report yet — will show "Generate" button
          }
          reportsList.push({
            candidate_id: c.candidate_id,
            candidate_name: c.full_name || c.email,
            candidate_email: c.email,
            report,
          });
        }
        setReports(reportsList);
      } catch (err) {
        console.error('Failed to fetch reports:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, [sessionId]);

  const handlePublish = useCallback(async (candidateId: string) => {
    try {
      const resp = await apiClient.post(
        `/api/reports/${sessionId}/${candidateId}/publish`
      );
      setReports((prev) =>
        prev.map((r) =>
          r.candidate_id === candidateId
            ? { ...r, report: resp.data }
            : r
        )
      );
      toast.success('Report published to candidate');
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to publish report');
    }
  }, [sessionId]);

  const handleSuppress = useCallback(async (candidateId: string) => {
    try {
      const resp = await apiClient.post(
        `/api/reports/${sessionId}/${candidateId}/suppress`
      );
      setReports((prev) =>
        prev.map((r) =>
          r.candidate_id === candidateId
            ? { ...r, report: resp.data }
            : r
        )
      );
      toast.success('Report suppressed — candidate will see "Report not available"');
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to suppress report');
    }
  }, [sessionId]);

  const handleGenerateReport = useCallback(async (candidateId: string) => {
    try {
      const resp = await apiClient.get(
        `/api/reports/${sessionId}/${candidateId}`
      );
      setReports((prev) =>
        prev.map((r) =>
          r.candidate_id === candidateId
            ? { ...r, report: resp.data }
            : r
        )
      );
      toast.success('Report generated');
    } catch (err: any) {
      toast.error(err?.response?.data?.detail || 'Failed to generate report');
    }
  }, [sessionId]);

  const handleDownloadPDF = useCallback((cr: CandidateReport) => {
    if (!cr.report) return;

    const doc = new jsPDF();
    const r = cr.report;

    doc.setFontSize(18);
    doc.text('SENTINEL — Integrity Report', 20, 20);

    doc.setFontSize(12);
    doc.text(`Session: ${sessionTitle}`, 20, 35);
    doc.text(`Candidate: ${cr.candidate_name}`, 20, 43);
    doc.text(`Email: ${cr.candidate_email}`, 20, 51);
    doc.text(`Generated: ${new Date(r.created_at).toLocaleString()}`, 20, 59);

    doc.setFontSize(16);
    doc.text(`Overall Integrity Score: ${r.overall_score}/100`, 20, 75);

    doc.setFontSize(11);
    const summaryLines = doc.splitTextToSize(r.summary, 170);
    doc.text(summaryLines, 20, 88);

    let yPos = 88 + summaryLines.length * 6 + 10;

    doc.setFontSize(13);
    doc.text('Event Breakdown', 20, yPos);
    yPos += 8;
    doc.setFontSize(10);
    doc.text(`Critical: ${r.event_count.critical || 0}  |  High: ${r.event_count.high || 0}  |  Medium: ${r.event_count.medium || 0}  |  Low: ${r.event_count.low || 0}`, 20, yPos);
    yPos += 12;

    if (r.timeline.length > 0) {
      doc.setFontSize(13);
      doc.text('Event Timeline', 20, yPos);
      yPos += 8;
      doc.setFontSize(9);
      for (const event of r.timeline.slice(0, 30)) {
        if (yPos > 270) {
          doc.addPage();
          yPos = 20;
        }
        const time = event.time ? new Date(event.time).toLocaleTimeString() : '--';
        doc.text(`${time}  [${event.severity}]  ${event.type}: ${event.description}`, 20, yPos);
        yPos += 5;
      }
    }

    doc.save(`SENTINEL_Report_${cr.candidate_name.replace(/\s+/g, '_')}.pdf`);
  }, [sessionTitle]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" message="Loading reports..." />
      </div>
    );
  }

  return (
    <ErrorBoundary name="ProctorReportPage">
      <div className="space-y-6">
        <div>
          <h1 className="text-2xl font-bold text-white">Session Reports</h1>
          <p className="text-gray-400 text-sm mt-1">{sessionTitle}</p>
        </div>

        {reports.length === 0 ? (
          <div className="text-center py-16 text-gray-500">
            <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" />
            <p>No candidates in this session.</p>
          </div>
        ) : (
          <div className="space-y-4">
            {reports.map((cr) => (
              <div
                key={cr.candidate_id}
                className="bg-gray-900 border border-gray-800 rounded-xl p-6"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="text-lg font-semibold text-white">{cr.candidate_name}</h3>
                    <p className="text-sm text-gray-500">{cr.candidate_email}</p>
                  </div>

                  {cr.report ? (
                    <div className="flex items-center gap-3">
                      {/* Score badge */}
                      <div
                        className="text-3xl font-bold"
                        style={{ color: getRiskColor(100 - cr.report.overall_score) }}
                      >
                        {cr.report.overall_score}
                      </div>

                      {/* Status badge */}
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium
                        ${cr.report.status === 'published' ? 'bg-green-600/20 text-green-400' :
                          cr.report.status === 'suppressed' ? 'bg-red-600/20 text-red-400' :
                          'bg-gray-600/20 text-gray-400'}`}>
                        {cr.report.status}
                      </span>
                    </div>
                  ) : (
                    <button
                      onClick={() => handleGenerateReport(cr.candidate_id)}
                      className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm
                                 font-medium rounded-lg transition-colors"
                    >
                      Generate Report
                    </button>
                  )}
                </div>

                {cr.report && (
                  <>
                    {/* Summary */}
                    <p className="text-sm text-gray-400 mt-4">{cr.report.summary}</p>

                    {/* Event counts */}
                    <div className="flex gap-4 mt-4">
                      {['critical', 'high', 'medium', 'low'].map((severity) => (
                        <div key={severity} className="text-center">
                          <div className={`text-lg font-bold ${
                            severity === 'critical' ? 'text-red-500' :
                            severity === 'high' ? 'text-orange-500' :
                            severity === 'medium' ? 'text-yellow-500' : 'text-green-500'
                          }`}>
                            {cr.report!.event_count[severity] || 0}
                          </div>
                          <div className="text-[10px] text-gray-600 capitalize">{severity}</div>
                        </div>
                      ))}
                    </div>

                    {/* Actions */}
                    <div className="flex gap-3 mt-5 pt-4 border-t border-gray-800">
                      {cr.report.status !== 'published' && (
                        <button
                          onClick={() => handlePublish(cr.candidate_id)}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-green-600 hover:bg-green-700
                                     text-white text-sm font-medium rounded-lg transition-colors"
                        >
                          <Send className="w-3.5 h-3.5" /> Publish
                        </button>
                      )}
                      {cr.report.status !== 'suppressed' && (
                        <button
                          onClick={() => handleSuppress(cr.candidate_id)}
                          className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600
                                     text-white text-sm font-medium rounded-lg transition-colors"
                        >
                          <EyeOff className="w-3.5 h-3.5" /> Suppress
                        </button>
                      )}
                      <button
                        onClick={() => handleDownloadPDF(cr)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-gray-700 hover:bg-gray-600
                                   text-white text-sm font-medium rounded-lg transition-colors"
                      >
                        <Download className="w-3.5 h-3.5" /> PDF
                      </button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </ErrorBoundary>
  );
}

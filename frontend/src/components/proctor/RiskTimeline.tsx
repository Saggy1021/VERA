// FILE: src/components/proctor/RiskTimeline.tsx
// Chart.js risk over time

'use client';

import { useMemo } from 'react';
import { Line } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  Title,
  Tooltip,
  Legend,
  Filler,
} from 'chart.js';

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler);

interface RiskDataPoint {
  time: string;
  score: number;
}

interface RiskTimelineProps {
  data: RiskDataPoint[];
  candidateName?: string;
}

export function RiskTimeline({ data, candidateName }: RiskTimelineProps) {
  const chartData = useMemo(() => ({
    labels: data.map((d) => d.time),
    datasets: [
      {
        label: 'Risk Score',
        data: data.map((d) => d.score),
        borderColor: '#ef4444',
        backgroundColor: 'rgba(239, 68, 68, 0.1)',
        borderWidth: 2,
        fill: true,
        tension: 0.4,
        pointRadius: 1,
        pointHoverRadius: 4,
      },
    ],
  }), [data]);

  const options = useMemo(() => ({
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false },
      title: {
        display: !!candidateName,
        text: candidateName ? `Risk Timeline — ${candidateName}` : '',
        color: '#9ca3af',
        font: { size: 12 },
      },
      tooltip: {
        backgroundColor: '#1f2937',
        borderColor: '#374151',
        borderWidth: 1,
        titleColor: '#f9fafb',
        bodyColor: '#d1d5db',
      },
    },
    scales: {
      x: {
        display: true,
        ticks: { color: '#6b7280', maxTicksLimit: 10, font: { size: 10 } },
        grid: { color: '#1f2937' },
      },
      y: {
        display: true,
        min: 0,
        max: 100,
        ticks: { color: '#6b7280', font: { size: 10 } },
        grid: { color: '#1f2937' },
      },
    },
  }), [candidateName]);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600 text-sm">
        No risk data yet. Score will appear as the session progresses.
      </div>
    );
  }

  return (
    <div className="h-full w-full">
      <Line data={chartData} options={options} />
    </div>
  );
}

export default RiskTimeline;

// FILE: src/lib/utils.ts
// cn(), formatDuration(), etc.

import { type ClassValue, clsx } from 'clsx';

/**
 * Utility for merging class names with clsx.
 */
export function cn(...inputs: ClassValue[]) {
  return clsx(inputs);
}

/**
 * Format a duration in minutes to a human-readable string.
 */
export function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
}

/**
 * Format a timestamp to a relative time string.
 */
export function formatRelativeTime(date: Date | string): string {
  const now = new Date();
  const target = new Date(date);
  const diffMs = now.getTime() - target.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHour = Math.floor(diffMin / 60);
  const diffDay = Math.floor(diffHour / 24);

  if (diffSec < 60) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  if (diffHour < 24) return `${diffHour}h ago`;
  return `${diffDay}d ago`;
}

/**
 * Format seconds into MM:SS timer display.
 */
export function formatTimer(totalSeconds: number): string {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
}

/**
 * Get risk level color based on score.
 */
export function getRiskColor(score: number): string {
  if (score < 25) return '#22c55e';   // green
  if (score < 50) return '#eab308';   // yellow
  if (score < 75) return '#f97316';   // orange
  return '#ef4444';                    // red
}

/**
 * Get risk level label based on score.
 */
export function getRiskLabel(score: number): string {
  if (score < 25) return 'Clean';
  if (score < 50) return 'Low';
  if (score < 75) return 'Medium';
  if (score < 90) return 'High';
  return 'Critical';
}

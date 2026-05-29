import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Map a 0..1 score to a colour. Null/undefined → neutral grey.
 * Used across the episode/cluster/recall/compare views.
 */
export function scoreColor(score: number | null | undefined): string {
  if (score == null || Number.isNaN(score)) return "#a1a1aa"; // zinc-400
  if (score >= 0.8) return "#22c55e"; // green-500
  if (score >= 0.5) return "#f59e0b"; // amber-500
  return "#ef4444"; // red-500
}

/**
 * Map an episode outcome to a badge modifier class suffix
 * (`badge badge-${outcomeClass(outcome)}`).
 */
export function outcomeClass(outcome: string | null | undefined): string {
  switch ((outcome || "").toLowerCase()) {
    case "success":
      return "success";
    case "failure":
      return "danger";
    case "partial":
      return "warning";
    default:
      return "muted";
  }
}

/** Format a latency in milliseconds as a human-readable string. */
export function fmtLatency(ms: number | null | undefined): string {
  if (ms == null || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** Format an ISO timestamp as a short, human-readable date/time. */
export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

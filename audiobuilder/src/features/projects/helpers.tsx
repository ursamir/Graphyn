import { Archive, CheckCircle2, Clock } from "lucide-react";
import type { Project } from "./types";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

export const STATUS_LABELS: Record<Project["status"], string> = {
  draft: "Draft",
  "in-progress": "In Progress",
  ready: "Ready",
  archived: "Archived",
};

export const STATUS_COLORS: Record<Project["status"], string> = {
  draft: "bg-secondary-100 text-secondary-700 dark:bg-secondary-700 dark:text-secondary-300",
  "in-progress": "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  ready: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  archived: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
};

export function StatusBadge({ status }: { status: Project["status"] }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_COLORS[status]}`}
    >
      {status === "archived" && <Archive className="h-3 w-3" />}
      {status === "ready" && <CheckCircle2 className="h-3 w-3" />}
      {status === "in-progress" && <Clock className="h-3 w-3" />}
      {STATUS_LABELS[status]}
    </span>
  );
}

export function formatDate(iso: string) {
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

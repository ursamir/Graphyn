import React from "react";
import { XCircle, AlertTriangle } from "lucide-react";

// ---------------------------------------------------------------------------
// SeverityBadge
// ---------------------------------------------------------------------------

export function SeverityBadge({ severity }: { severity: "error" | "warning" }) {
  return severity === "error" ? (
    <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-900/40 dark:text-red-300">
      <XCircle className="h-3 w-3" /> Error
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
      <AlertTriangle className="h-3 w-3" /> Warning
    </span>
  );
}

// ---------------------------------------------------------------------------
// Card — local card (not the shared components/Card.tsx)
// ---------------------------------------------------------------------------

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div
      className={`rounded-xl border border-secondary-200 bg-white p-4 shadow-sm dark:border-secondary-700 dark:bg-secondary-800 ${className}`}
    >
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SectionTitle
// ---------------------------------------------------------------------------

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 className="mb-3 text-sm font-semibold text-secondary-700 dark:text-secondary-300">
      {children}
    </h3>
  );
}

import React from "react";
import { ShieldCheck, ShieldX, Loader2 } from "lucide-react";
import { apiUrl } from "../../utils/api";
import type { ExportGate } from "./types";

// ---------------------------------------------------------------------------
// Export Gate Banner
// ---------------------------------------------------------------------------

export function ExportGateBanner({
  projectName,
  refreshKey,
}: {
  projectName: string;
  refreshKey: number;
}) {
  const [gate, setGate] = React.useState<ExportGate | null>(null);
  const [loading, setLoading] = React.useState(false);

  React.useEffect(() => {
    if (!projectName) return;
    setLoading(true);
    fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/export-gate`))
      .then((r) => (r.ok ? (r.json() as Promise<ExportGate>) : null))
      .then((data) => setGate(data))
      .catch(() => setGate(null))
      .finally(() => setLoading(false));
  }, [projectName, refreshKey]);

  if (loading) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-secondary-200 bg-secondary-50 px-4 py-3 text-sm text-secondary-500 dark:border-secondary-700 dark:bg-secondary-800">
        <Loader2 className="h-4 w-4 animate-spin" />
        Checking export readiness…
      </div>
    );
  }

  if (!gate) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-secondary-200 bg-secondary-50 px-4 py-3 text-sm text-secondary-500 dark:border-secondary-700 dark:bg-secondary-800">
        Run quality checks first to determine export readiness.
      </div>
    );
  }

  if (gate.can_export) {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-green-300 bg-green-50 px-4 py-3 text-sm text-green-700 dark:border-green-700 dark:bg-green-900/20 dark:text-green-300">
        <ShieldCheck className="h-4 w-4 shrink-0" />
        <strong>✓ Ready to export</strong>
      </div>
    );
  }

  if (gate.blocking_issues.length > 0) {
    return (
      <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 dark:border-red-700 dark:bg-red-900/20">
        <div className="flex items-center gap-2 text-sm font-semibold text-red-700 dark:text-red-300">
          <ShieldX className="h-4 w-4 shrink-0" />
          ✗ Export blocked: {gate.blocking_issues.length} issue
          {gate.blocking_issues.length !== 1 ? "s" : ""}
        </div>
        <ul className="mt-2 space-y-1 pl-6 text-xs text-red-600 dark:text-red-400">
          {gate.blocking_issues.slice(0, 5).map((issue, i) => (
            <li key={i} className="list-disc">
              <span className="font-semibold">{issue.check_name}</span>: {issue.detail}
            </li>
          ))}
          {gate.blocking_issues.length > 5 && (
            <li className="list-none text-red-500">
              …and {gate.blocking_issues.length - 5} more
            </li>
          )}
        </ul>
      </div>
    );
  }

  // can_export === false and blocking_issues.length === 0 → neutral
  return (
    <div className="flex items-center gap-2 rounded-lg border border-secondary-200 bg-secondary-50 px-4 py-3 text-sm text-secondary-500 dark:border-secondary-700 dark:bg-secondary-800">
      Run quality checks first to determine export readiness.
    </div>
  );
}

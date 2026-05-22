import React from "react";
import { Download } from "lucide-react";
import { apiUrl } from "../../utils/api";

// ---------------------------------------------------------------------------
// Quality Report Export Button
// ---------------------------------------------------------------------------

export function QualityReportExport({
  projectName,
  version,
}: {
  projectName: string;
  version: string;
}) {
  const [downloading, setDownloading] = React.useState(false);

  const handleDownload = async (format: "csv" | "json") => {
    if (!projectName || !version) return;
    setDownloading(true);
    try {
      const url = apiUrl(
        `/projects/${encodeURIComponent(projectName)}/quality-report/export`,
        { format },
      );
      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `quality-report-${projectName}-${version}.${format}`;
      a.click();
      URL.revokeObjectURL(a.href);
    } catch {
      // silently ignore — user can retry
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-secondary-500">Export report:</span>
      <button
        type="button"
        disabled={downloading || !projectName || !version}
        onClick={() => void handleDownload("csv")}
        className="inline-flex items-center gap-1 rounded border border-secondary-300 bg-white px-2.5 py-1 text-xs font-medium text-secondary-700 transition-colors hover:bg-secondary-50 disabled:opacity-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
      >
        <Download className="h-3 w-3" /> CSV
      </button>
      <button
        type="button"
        disabled={downloading || !projectName || !version}
        onClick={() => void handleDownload("json")}
        className="inline-flex items-center gap-1 rounded border border-secondary-300 bg-white px-2.5 py-1 text-xs font-medium text-secondary-700 transition-colors hover:bg-secondary-50 disabled:opacity-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
      >
        <Download className="h-3 w-3" /> JSON
      </button>
    </div>
  );
}

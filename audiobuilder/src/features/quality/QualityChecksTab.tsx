import React from "react";
import {
  Play,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Download,
  Loader2,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import { apiUrl } from "../../utils/api";
import type { Finding, CheckJob } from "./types";
import { SeverityBadge, Card } from "./components";

// ---------------------------------------------------------------------------
// Quality Checks Tab
// ---------------------------------------------------------------------------

export function QualityChecksTab({
  projectName,
  onCheckComplete,
}: {
  projectName: string;
  onCheckComplete?: (findings: Finding[]) => void;
}) {
  const [jobId, setJobId] = React.useState<string | null>(null);
  const [job, setJob] = React.useState<CheckJob | null>(null);
  const [running, setRunning] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [downloadError, setDownloadError] = React.useState<string | null>(null);
  const [expanded, setExpanded] = React.useState<Set<string>>(new Set());
  const pollRef = React.useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  React.useEffect(() => () => stopPolling(), []);

  const pollJob = React.useCallback(
    async (id: string) => {
      try {
        const res = await fetch(
          apiUrl(
            `/projects/${encodeURIComponent(projectName)}/quality-check/${encodeURIComponent(id)}`,
          ),
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = (await res.json()) as CheckJob;
        setJob(data);
        if (data.status !== "running") {
          stopPolling();
          setRunning(false);
          if (data.status === "completed" && onCheckComplete) {
            onCheckComplete(data.findings);
          }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Poll failed");
        stopPolling();
        setRunning(false);
      }
    },
    [projectName, onCheckComplete],
  );

  const handleRunChecks = async () => {
    if (!projectName) return;
    setError(null);
    setJob(null);
    setJobId(null);
    setRunning(true);
    try {
      const res = await fetch(
        apiUrl(`/projects/${encodeURIComponent(projectName)}/quality-check`),
        { method: "POST" },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { job_id: string };
      setJobId(data.job_id);
      pollRef.current = setInterval(() => void pollJob(data.job_id), 2000);
      void pollJob(data.job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start check");
      setRunning(false);
    }
  };

  const handleDownloadJSON = async () => {
    if (!projectName) return;
    setDownloadError(null);
    try {
      const res = await fetch(
        apiUrl(`/projects/${encodeURIComponent(projectName)}/quality-report/export`, { format: "json" }),
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      const blob = new Blob([text], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "quality_report.json";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : "Download failed");
    }
  };

  const handleDownloadCSV = async () => {
    if (!projectName) return;
    setDownloadError(null);
    try {
      const res = await fetch(
        apiUrl(`/projects/${encodeURIComponent(projectName)}/quality-report/export`, { format: "csv" }),
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      const blob = new Blob([text], { type: "text/csv" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "quality_report.csv";
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (err) {
      setDownloadError(err instanceof Error ? err.message : "Download failed");
    }
  };

  const grouped = React.useMemo(() => {
    if (!job?.findings) return {} as Record<string, Finding[]>;
    return job.findings.reduce<Record<string, Finding[]>>((acc, f) => {
      (acc[f.check_name] ??= []).push(f);
      return acc;
    }, {});
  }, [job]);

  const toggleGroup = (name: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          onClick={() => void handleRunChecks()}
          disabled={running || !projectName}
          className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
        >
          {running ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {running ? "Running…" : "Run Checks"}
        </button>
        <button
          type="button"
          disabled={job === null || !projectName}
          onClick={() => void handleDownloadJSON()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm font-medium text-secondary-700 transition-colors hover:bg-secondary-50 disabled:opacity-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
        >
          <Download className="h-4 w-4" />
          Download JSON
        </button>
        <button
          type="button"
          disabled={job === null || !projectName}
          onClick={() => void handleDownloadCSV()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm font-medium text-secondary-700 transition-colors hover:bg-secondary-50 disabled:opacity-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
        >
          <Download className="h-4 w-4" />
          Download CSV
        </button>
        {jobId && (
          <span className="text-xs text-secondary-500">Job: {jobId}</span>
        )}
      </div>

      {downloadError && (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700 dark:bg-red-900/20 dark:text-red-300">
          {downloadError}
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700 dark:bg-red-900/20 dark:text-red-300">
          {error}
        </div>
      )}

      {job?.status === "completed" && job.findings.length === 0 && (
        <div className="flex items-center gap-2 rounded-lg border border-green-300 bg-green-50 px-4 py-3 text-sm text-green-700 dark:border-green-700 dark:bg-green-900/20 dark:text-green-300">
          <CheckCircle2 className="h-4 w-4" />
          No issues found — dataset looks clean!
        </div>
      )}

      {Object.entries(grouped).map(([checkName, findings]) => {
        const isOpen = expanded.has(checkName);
        const errorCount = findings.filter((f) => f.severity === "error").length;
        const warnCount = findings.filter((f) => f.severity === "warning").length;
        return (
          <Card key={checkName}>
            <button
              type="button"
              onClick={() => toggleGroup(checkName)}
              className="flex w-full items-center justify-between text-left"
            >
              <div className="flex items-center gap-2">
                {isOpen ? (
                  <ChevronDown className="h-4 w-4 text-secondary-500" />
                ) : (
                  <ChevronRight className="h-4 w-4 text-secondary-500" />
                )}
                <span className="text-sm font-semibold text-secondary-900 dark:text-secondary-100">
                  {checkName}
                </span>
                <span className="text-xs text-secondary-500">
                  {findings.length} sample{findings.length !== 1 ? "s" : ""}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                {errorCount > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700 dark:bg-red-900/40 dark:text-red-300">
                    <XCircle className="h-3 w-3" /> {errorCount}
                  </span>
                )}
                {warnCount > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                    <AlertTriangle className="h-3 w-3" /> {warnCount}
                  </span>
                )}
              </div>
            </button>

            {isOpen && (
              <div className="mt-3 overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-secondary-200 dark:border-secondary-700">
                      <th className="pb-1.5 text-left font-semibold text-secondary-600 dark:text-secondary-400">
                        Sample
                      </th>
                      <th className="pb-1.5 text-left font-semibold text-secondary-600 dark:text-secondary-400">
                        Severity
                      </th>
                      <th className="pb-1.5 text-left font-semibold text-secondary-600 dark:text-secondary-400">
                        Detail
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {findings.map((f, i) => (
                      <tr
                        key={i}
                        className="border-b border-secondary-100 last:border-0 dark:border-secondary-700/50"
                      >
                        <td className="max-w-[200px] truncate py-1.5 pr-3 font-mono text-secondary-700 dark:text-secondary-300">
                          {f.sample_path.split("/").pop()}
                        </td>
                        <td className="py-1.5 pr-3">
                          <SeverityBadge severity={f.severity} />
                        </td>
                        <td className="py-1.5 text-secondary-600 dark:text-secondary-400">
                          {f.detail}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        );
      })}

      {!job && !running && !error && (
        <div className="py-12 text-center text-sm text-secondary-500">
          Click "Run Checks" to analyse the dataset for quality issues.
        </div>
      )}
    </div>
  );
}

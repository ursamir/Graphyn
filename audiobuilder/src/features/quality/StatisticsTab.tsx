import React from "react";
import { RefreshCw, AlertTriangle, Loader2 } from "lucide-react";
import { apiUrl } from "../../utils/api";
import type { Stats } from "./types";
import { BAR_COLORS, BarChartSVG, PieChartSVG } from "./charts";
import { Card, SectionTitle } from "./components";

// ---------------------------------------------------------------------------
// Statistics Tab
// ---------------------------------------------------------------------------

export function StatisticsTab({
  projectName,
  version,
}: {
  projectName: string;
  version: string;
}) {
  const [stats, setStats] = React.useState<Stats | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const fetchStats = React.useCallback(async () => {
    if (!projectName || !version) return;
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(
        apiUrl(
          `/projects/${encodeURIComponent(projectName)}/versions/${encodeURIComponent(version)}/stats`,
        ),
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as Stats;
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load stats");
    } finally {
      setLoading(false);
    }
  }, [projectName, version]);

  React.useEffect(() => {
    void fetchStats();
  }, [fetchStats]);

  const labelData = stats
    ? Object.entries(stats.label_distribution).map(([label, value]) => ({ label, value }))
    : [];

  const sampleRateData = stats
    ? Object.entries(stats.sample_rate_distribution).map(([label, value]) => ({ label, value }))
    : [];

  const durationData = stats
    ? stats.duration_histogram.map((h) => ({ label: h.bin, value: h.count }))
    : [];

  const snrData = stats
    ? stats.snr_histogram.map((h) => ({ label: h.bin, value: h.count }))
    : [];

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex items-center justify-between">
        <div className="flex gap-4 text-sm text-secondary-600 dark:text-secondary-400">
          {stats && (
            <>
              <span>
                <strong className="text-secondary-900 dark:text-secondary-100">
                  {stats.total_samples}
                </strong>{" "}
                samples
              </span>
              <span>
                <strong className="text-secondary-900 dark:text-secondary-100">
                  {stats.total_duration_s.toFixed(1)}s
                </strong>{" "}
                total duration
              </span>
            </>
          )}
        </div>
        <button
          type="button"
          onClick={() => void fetchStats()}
          disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-secondary-300 bg-white px-3 py-1.5 text-xs font-medium text-secondary-700 transition-colors hover:bg-secondary-50 disabled:opacity-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Class imbalance warning */}
      {stats?.class_imbalance_warning && (
        <div className="flex items-start gap-2 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-300">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <strong>Class imbalance detected.</strong> Labels below 20% of mean count:{" "}
            {stats.imbalanced_labels?.join(", ") ?? "unknown"}.
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-700 dark:bg-red-900/20 dark:text-red-300">
          {error}
        </div>
      )}

      {loading && !stats && (
        <div className="flex items-center justify-center py-12 text-secondary-500">
          <Loader2 className="h-6 w-6 animate-spin" />
        </div>
      )}

      {!loading && !stats && !error && (
        <div className="py-12 text-center text-sm text-secondary-500">
          Select a project and version to view statistics.
        </div>
      )}

      {stats && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card>
            <SectionTitle>Label Distribution</SectionTitle>
            <BarChartSVG data={labelData} color={BAR_COLORS[0]} />
          </Card>

          <Card>
            <SectionTitle>Duration Distribution</SectionTitle>
            <BarChartSVG data={durationData} color={BAR_COLORS[1]} />
          </Card>

          <Card>
            <SectionTitle>Sample Rate Distribution</SectionTitle>
            <PieChartSVG data={sampleRateData} />
          </Card>

          <Card>
            <SectionTitle>SNR Distribution</SectionTitle>
            <BarChartSVG data={snrData} color={BAR_COLORS[4]} />
          </Card>
        </div>
      )}
    </div>
  );
}

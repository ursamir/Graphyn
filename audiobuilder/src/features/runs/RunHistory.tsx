// audiobuilder/src/features/runs/RunHistory.tsx
import React from "react";
import {
  RefreshCw,
  CheckCircle,
  XCircle,
  Clock,
  ChevronDown,
  ChevronRight,
  FileText,
  Play,
  ScrollText,
  Code2,
  Timer,
  ArrowUpDown,
  Filter,
} from "lucide-react";
import { apiUrl } from "../../utils/api";

interface RunSummary {
  run_id: string;
  created_at: string | null;
  status: "completed" | "failed" | "running" | "unknown";
  had_error: boolean;
  log_count: number;
  has_config: boolean;
}

interface NodeStat {
  node_type: string;
  node_index: number;
  duration_s: number;
  input_count: number;
  output_count: number;
}

interface RunDetail {
  run_id: string;
  meta: Record<string, unknown>;
  config_yaml: string | null;
  logs: Array<{ time?: string; level?: string; message?: string }>;
}

interface RunHistoryProps {
  onRerun?: (configYaml: string) => void;
}

type StatusFilter = "all" | "completed" | "failed";
type SortKey = "date_desc" | "date_asc" | "duration_desc" | "duration_asc";

function StatusIcon({ status }: { status: RunSummary["status"] }) {
  if (status === "completed")
    return <CheckCircle className="w-4 h-4 text-green-500 shrink-0" />;
  if (status === "failed")
    return <XCircle className="w-4 h-4 text-red-500 shrink-0" />;
  return <Clock className="w-4 h-4 text-yellow-500 shrink-0" />;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function formatDuration(s: number | undefined | null): string {
  if (s == null) return "—";
  if (s < 60) return `${s.toFixed(1)}s`;
  const m = Math.floor(s / 60);
  const rem = (s % 60).toFixed(0).padStart(2, "0");
  return `${m}m ${rem}s`;
}

async function loadRuns(): Promise<RunSummary[]> {
  const r = await fetch(apiUrl("/runs"));
  return r.json() as Promise<RunSummary[]>;
}

async function loadRunDetail(runId: string): Promise<RunDetail> {
  const r = await fetch(apiUrl(`/run/${runId}`));
  return r.json() as Promise<RunDetail>;
}

// Sub-panel: per-node timing breakdown
function NodeTimingTable({ nodeStats }: { nodeStats: NodeStat[] }) {
  if (nodeStats.length === 0) return null;
  const maxDuration = Math.max(...nodeStats.map((n) => n.duration_s));

  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400 mb-1 flex items-center gap-1">
        <Timer className="w-3 h-3" /> Node Timing
      </p>
      <div className="rounded-lg overflow-hidden border border-secondary-200 dark:border-secondary-700">
        <table className="w-full text-[10px]">
          <thead>
            <tr className="bg-secondary-100 dark:bg-secondary-800 text-secondary-500 dark:text-secondary-400">
              <th className="text-left px-2 py-1 font-semibold">#</th>
              <th className="text-left px-2 py-1 font-semibold">Node</th>
              <th className="text-right px-2 py-1 font-semibold">Duration</th>
              <th className="text-right px-2 py-1 font-semibold">In</th>
              <th className="text-right px-2 py-1 font-semibold">Out</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-secondary-100 dark:divide-secondary-800">
            {nodeStats.map((n) => {
              const isSlowest = n.duration_s === maxDuration && maxDuration > 0;
              return (
                <tr
                  key={n.node_index}
                  className={`${
                    isSlowest
                      ? "bg-amber-50 dark:bg-amber-900/20"
                      : "bg-white dark:bg-secondary-900"
                  }`}
                >
                  <td className="px-2 py-1 font-mono text-secondary-400">
                    {n.node_index}
                  </td>
                  <td className="px-2 py-1 font-mono text-secondary-800 dark:text-secondary-200 flex items-center gap-1">
                    {n.node_type}
                    {isSlowest && (
                      <span className="text-[9px] text-amber-600 dark:text-amber-400 font-semibold">
                        slowest
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-1 text-right font-mono text-secondary-700 dark:text-secondary-300">
                    {formatDuration(n.duration_s)}
                  </td>
                  <td className="px-2 py-1 text-right text-secondary-500 dark:text-secondary-400">
                    {n.input_count}
                  </td>
                  <td className="px-2 py-1 text-right text-secondary-500 dark:text-secondary-400">
                    {n.output_count}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function RunHistory({ onRerun }: RunHistoryProps) {
  // null = not yet fetched; RunSummary[] = fetched (may be empty)
  const [runs, setRuns] = React.useState<RunSummary[] | null>(null);
  const [refreshKey, setRefreshKey] = React.useState(0);
  const [expandedId, setExpandedId] = React.useState<string | null>(null);
  const [detail, setDetail] = React.useState<RunDetail | null>(null);
  const [detailLoading, setDetailLoading] = React.useState(false);

  // Active sub-panel within expanded row: "logs" | "config" | "timing"
  const [activePanel, setActivePanel] = React.useState<"logs" | "config" | "timing" | null>(null);

  // Filters & sort
  const [statusFilter, setStatusFilter] = React.useState<StatusFilter>("all");
  const [sortKey, setSortKey] = React.useState<SortKey>("date_desc");

  // Fetch runs whenever refreshKey changes
  React.useEffect(() => {
    let cancelled = false;
    loadRuns()
      .then((data) => {
        if (!cancelled) setRuns(data);
      })
      .catch(() => {
        if (!cancelled) setRuns([]);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshKey]);

  const handleRefresh = () => {
    setRuns(null); // show loading state
    setRefreshKey((k) => k + 1);
  };

  const toggleExpand = (runId: string) => {
    if (expandedId === runId) {
      setExpandedId(null);
      setDetail(null);
      setActivePanel(null);
      return;
    }
    setExpandedId(runId);
    setDetail(null);
    setActivePanel(null);
    setDetailLoading(true);
    loadRunDetail(runId)
      .then((d) => setDetail(d))
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  };

  const handleRerun = (d: RunDetail) => {
    if (!d.config_yaml) return;
    const confirmed = window.confirm(
      `Load config from run ${d.run_id} into the canvas and re-run?\n\nThis will replace the current canvas contents.`
    );
    if (!confirmed) return;
    if (onRerun) {
      onRerun(d.config_yaml);
    }
  };

  // Derived: filtered + sorted runs
  const displayedRuns = React.useMemo(() => {
    if (!runs) return [];
    let filtered = runs;
    if (statusFilter !== "all") {
      filtered = filtered.filter((r) => r.status === statusFilter);
    }
    const sorted = [...filtered].sort((a, b) => {
      if (sortKey === "date_desc" || sortKey === "date_asc") {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
        return sortKey === "date_desc" ? tb - ta : ta - tb;
      }
      // duration sort — read from meta if available; fall back to 0
      // We don't have duration in RunSummary, so sort by run_id as proxy
      // (duration is only in detail; for summary list we keep date order)
      return 0;
    });
    return sorted;
  }, [runs, statusFilter, sortKey]);

  const loading = runs === null;

  return (
    <div className="flex flex-col h-full bg-white dark:bg-secondary-900">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-secondary-200 dark:border-secondary-700 bg-secondary-50 dark:bg-secondary-800">
        <h3 className="text-sm font-bold text-secondary-900 dark:text-secondary-100">
          Run History
        </h3>
        <button
          onClick={handleRefresh}
          disabled={loading}
          className="p-1.5 rounded-md hover:bg-secondary-200 dark:hover:bg-secondary-700 text-secondary-500 dark:text-secondary-400 disabled:opacity-50"
          title="Refresh run history"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin" : ""}`} />
        </button>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-secondary-100 dark:border-secondary-800 bg-secondary-50/50 dark:bg-secondary-800/50 flex-wrap">
        {/* Status filter */}
        <div className="flex items-center gap-1">
          <Filter className="w-3 h-3 text-secondary-400 shrink-0" />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as StatusFilter)}
            className="text-[11px] rounded border border-secondary-200 dark:border-secondary-600 bg-white dark:bg-secondary-700 text-secondary-700 dark:text-secondary-200 px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-primary-400"
            aria-label="Filter by status"
          >
            <option value="all">All</option>
            <option value="completed">Completed</option>
            <option value="failed">Failed</option>
          </select>
        </div>

        {/* Sort */}
        <div className="flex items-center gap-1">
          <ArrowUpDown className="w-3 h-3 text-secondary-400 shrink-0" />
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            className="text-[11px] rounded border border-secondary-200 dark:border-secondary-600 bg-white dark:bg-secondary-700 text-secondary-700 dark:text-secondary-200 px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-primary-400"
            aria-label="Sort runs"
          >
            <option value="date_desc">Date ↓</option>
            <option value="date_asc">Date ↑</option>
          </select>
        </div>

        {runs && (
          <span className="ml-auto text-[10px] text-secondary-400 dark:text-secondary-500">
            {displayedRuns.length} / {runs.length}
          </span>
        )}
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto divide-y divide-secondary-100 dark:divide-secondary-800">
        {loading && (
          <div className="px-4 py-8 text-center text-sm text-secondary-400 dark:text-secondary-500">
            Loading…
          </div>
        )}

        {!loading && displayedRuns.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-secondary-400 dark:text-secondary-500">
            {runs!.length === 0
              ? "No runs yet. Run a pipeline to see history here."
              : "No runs match the current filter."}
          </div>
        )}

        {!loading &&
          displayedRuns.map((run) => (
            <div key={run.run_id}>
              {/* Summary row */}
              <button
                type="button"
                onClick={() => toggleExpand(run.run_id)}
                className="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-secondary-50 dark:hover:bg-secondary-800/60 transition-colors"
              >
                {expandedId === run.run_id ? (
                  <ChevronDown className="w-3.5 h-3.5 text-secondary-400 shrink-0" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5 text-secondary-400 shrink-0" />
                )}
                <StatusIcon status={run.status} />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-xs font-mono font-semibold text-secondary-800 dark:text-secondary-200">
                      {run.run_id}
                    </span>
                    <span
                      className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${
                        run.status === "completed"
                          ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                          : run.status === "failed"
                            ? "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400"
                            : "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
                      }`}
                    >
                      {run.status}
                    </span>
                  </div>
                  <div className="text-[11px] text-secondary-500 dark:text-secondary-400 mt-0.5">
                    {formatDate(run.created_at)} · {run.log_count} log entries
                  </div>
                </div>
              </button>

              {/* Expanded detail */}
              {expandedId === run.run_id && (
                <div className="px-4 pb-4 bg-secondary-50/60 dark:bg-secondary-800/40 border-t border-secondary-100 dark:border-secondary-700">
                  {detailLoading && (
                    <p className="text-xs text-secondary-400 py-3">Loading…</p>
                  )}

                  {!detailLoading && detail && (
                    <div className="space-y-3 pt-3">
                      {/* Output stats row */}
                      {(() => {
                        const durationS = detail.meta.duration_s as number | undefined;
                        const outputCount = detail.meta.output_sample_count as number | undefined;
                        if (durationS == null && outputCount == null) return null;
                        return (
                          <div className="flex items-center gap-4 text-[11px] bg-secondary-100 dark:bg-secondary-900 rounded-lg px-3 py-2">
                            {durationS != null && (
                              <div className="flex items-center gap-1.5">
                                <Timer className="w-3 h-3 text-secondary-400" />
                                <span className="text-secondary-500 dark:text-secondary-400">Duration:</span>
                                <span className="font-semibold text-secondary-800 dark:text-secondary-200 font-mono">
                                  {formatDuration(durationS)}
                                </span>
                              </div>
                            )}
                            {outputCount != null && (
                              <div className="flex items-center gap-1.5">
                                <CheckCircle className="w-3 h-3 text-green-500" />
                                <span className="text-secondary-500 dark:text-secondary-400">Samples:</span>
                                <span className="font-semibold text-secondary-800 dark:text-secondary-200 font-mono">
                                  {outputCount}
                                </span>
                              </div>
                            )}
                          </div>
                        );
                      })()}

                      {/* Action buttons */}
                      <div className="flex items-center gap-2 flex-wrap">
                        {/* Re-run */}
                        {detail.config_yaml && onRerun && (
                          <button
                            type="button"
                            onClick={() => handleRerun(detail)}
                            className="inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-md bg-primary-600 text-white hover:bg-primary-700 transition-colors"
                            title="Load this config into the canvas and re-run"
                          >
                            <Play className="w-3 h-3" />
                            Re-run
                          </button>
                        )}

                        {/* View Logs */}
                        {detail.logs.length > 0 && (
                          <button
                            type="button"
                            onClick={() =>
                              setActivePanel(activePanel === "logs" ? null : "logs")
                            }
                            className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-md transition-colors ${
                              activePanel === "logs"
                                ? "bg-secondary-700 text-white"
                                : "bg-secondary-200 dark:bg-secondary-700 text-secondary-700 dark:text-secondary-200 hover:bg-secondary-300 dark:hover:bg-secondary-600"
                            }`}
                            title="View run logs"
                          >
                            <ScrollText className="w-3 h-3" />
                            View Logs
                          </button>
                        )}

                        {/* View Config */}
                        {detail.config_yaml && (
                          <button
                            type="button"
                            onClick={() =>
                              setActivePanel(activePanel === "config" ? null : "config")
                            }
                            className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-md transition-colors ${
                              activePanel === "config"
                                ? "bg-secondary-700 text-white"
                                : "bg-secondary-200 dark:bg-secondary-700 text-secondary-700 dark:text-secondary-200 hover:bg-secondary-300 dark:hover:bg-secondary-600"
                            }`}
                            title="View pipeline config YAML"
                          >
                            <Code2 className="w-3 h-3" />
                            View Config
                          </button>
                        )}

                        {/* Node Timing */}
                        {Array.isArray(detail.meta.node_stats) &&
                          (detail.meta.node_stats as NodeStat[]).length > 0 && (
                            <button
                              type="button"
                              onClick={() =>
                                setActivePanel(activePanel === "timing" ? null : "timing")
                              }
                              className={`inline-flex items-center gap-1 text-[11px] font-semibold px-2.5 py-1 rounded-md transition-colors ${
                                activePanel === "timing"
                                  ? "bg-secondary-700 text-white"
                                  : "bg-secondary-200 dark:bg-secondary-700 text-secondary-700 dark:text-secondary-200 hover:bg-secondary-300 dark:hover:bg-secondary-600"
                              }`}
                              title="View per-node timing breakdown"
                            >
                              <Timer className="w-3 h-3" />
                              Timing
                            </button>
                          )}
                      </div>

                      {/* Active sub-panel: Logs */}
                      {activePanel === "logs" && detail.logs.length > 0 && (
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400 mb-1">
                            Logs ({detail.logs.length})
                          </p>
                          <div className="bg-secondary-900 dark:bg-black rounded-lg p-2 max-h-48 overflow-y-auto space-y-0.5">
                            {detail.logs.map((entry, i) => (
                              <div
                                key={i}
                                className={`text-[10px] font-mono ${
                                  entry.level === "ERROR"
                                    ? "text-red-400"
                                    : entry.level === "WARNING"
                                      ? "text-yellow-400"
                                      : "text-green-400"
                                }`}
                              >
                                <span className="text-secondary-500 mr-1">
                                  [{entry.level ?? "INFO"}]
                                </span>
                                {entry.time && (
                                  <span className="text-secondary-600 mr-1 text-[9px]">
                                    {entry.time}
                                  </span>
                                )}
                                {entry.message ?? ""}
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Active sub-panel: Config */}
                      {activePanel === "config" && detail.config_yaml && (
                        <div>
                          <p className="text-[10px] font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400 mb-1 flex items-center gap-1">
                            <FileText className="w-3 h-3" /> Pipeline Config (read-only)
                          </p>
                          <pre className="text-[10px] font-mono bg-secondary-900 dark:bg-black text-green-400 rounded-lg p-2 overflow-x-auto max-h-48 whitespace-pre-wrap select-all">
                            {detail.config_yaml}
                          </pre>
                        </div>
                      )}

                      {/* Active sub-panel: Node timing */}
                      {activePanel === "timing" &&
                        Array.isArray(detail.meta.node_stats) && (
                          <NodeTimingTable
                            nodeStats={detail.meta.node_stats as NodeStat[]}
                          />
                        )}

                      {/* Metadata (always shown, collapsed to key fields) */}
                      {Object.keys(detail.meta).length > 0 && (
                        <details className="group">
                          <summary className="text-[10px] font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400 cursor-pointer select-none list-none flex items-center gap-1">
                            <ChevronRight className="w-3 h-3 group-open:rotate-90 transition-transform" />
                            Raw Metadata
                          </summary>
                          <div className="mt-1 text-[11px] font-mono bg-secondary-100 dark:bg-secondary-900 rounded-lg p-2 space-y-0.5">
                            {Object.entries(detail.meta).map(([k, v]) => (
                              <div key={k} className="flex gap-2">
                                <span className="text-secondary-500 dark:text-secondary-400 shrink-0">
                                  {k}:
                                </span>
                                <span className="text-secondary-800 dark:text-secondary-200 break-all">
                                  {typeof v === "object"
                                    ? JSON.stringify(v)
                                    : String(v)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
      </div>
    </div>
  );
}

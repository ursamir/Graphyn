import React from "react";
import { apiUrl } from "../../utils/api";
import DatasetHeader from "./DatasetHeader";
import DatasetResults from "./DatasetResults";
import DatasetSidebar from "./DatasetSidebar";
import DatasetStats from "./DatasetStats";
import { groupGeneratedRows, groupInputRows } from "./utils";
import type {
  AudioRow,
  DatasetMode,
  DatasetSummary,
  InputLabelSummary,
} from "./types";

// ---------------------------------------------------------------------------
// IngestURLDialog
// ---------------------------------------------------------------------------

interface ProgressEntry {
  url: string;
  status: "pending" | "success" | "error";
  message?: string;
}

interface IngestSummary {
  total_files: number;
  total_duration_seconds: number;
  label_distribution: Record<string, number>;
}

interface IngestURLDialogProps {
  onClose: () => void;
  onComplete: () => void;
}

function IngestURLDialog({ onClose, onComplete }: IngestURLDialogProps) {
  const [urlsText, setUrlsText] = React.useState("");
  const [label, setLabel] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [progress, setProgress] = React.useState<ProgressEntry[]>([]);
  const [summary, setSummary] = React.useState<IngestSummary | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const esRef = React.useRef<EventSource | null>(null);

  // Clean up EventSource when dialog unmounts
  React.useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  const handleClose = () => {
    esRef.current?.close();
    esRef.current = null;
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const urls = urlsText
      .split("\n")
      .map((l) => l.trim())
      .filter(Boolean);
    if (urls.length === 0) {
      setError("Please enter at least one URL.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setProgress(urls.map((url) => ({ url, status: "pending" })));
    setSummary(null);

    let jobId: string;
    try {
      const res = await fetch(apiUrl("/ingest/url"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ urls, label }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { job_id: string };
      jobId = data.job_id;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start ingestion job.");
      setSubmitting(false);
      return;
    }

    // Open SSE stream
    const es = new EventSource(apiUrl(`/ingest/url/${jobId}/stream`));
    esRef.current = es;

    es.onmessage = (event) => {
      let parsed: { type: string; url?: string; status?: string; message?: string; total_files?: number; total_duration_seconds?: number; label_distribution?: Record<string, number> };
      try {
        parsed = JSON.parse(event.data) as typeof parsed;
      } catch {
        return;
      }

      // Backend sends type="progress" for per-file updates
      if (parsed.type === "progress") {
        const { url: doneUrl, status, message } = parsed;
        if (doneUrl) {
          setProgress((prev) =>
            prev.map((entry) =>
              entry.url === doneUrl
                ? { ...entry, status: (status as "success" | "error") ?? "success", message }
                : entry,
            ),
          );
        }
      } else if (parsed.type === "summary") {
        setSummary({
          total_files: parsed.total_files ?? 0,
          total_duration_seconds: parsed.total_duration_seconds ?? 0,
          label_distribution: parsed.label_distribution ?? {},
        });
        es.close();
        esRef.current = null;
        setSubmitting(false);
        onComplete();
      }
    };

    es.onerror = () => {
      setError("Stream connection lost. The job may still be running in the background.");
      es.close();
      esRef.current = null;
      setSubmitting(false);
    };
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ingest-url-title"
    >
      <div className="w-full max-w-lg rounded-xl bg-white shadow-2xl dark:bg-gray-900">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4 dark:border-gray-700">
          <h2 id="ingest-url-title" className="text-base font-semibold text-gray-900 dark:text-gray-100">
            Ingest from URL
          </h2>
          <button
            type="button"
            onClick={handleClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-300"
            aria-label="Close dialog"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <form onSubmit={(e) => { void handleSubmit(e); }} className="space-y-4 px-6 py-4">
          <div>
            <label
              htmlFor="ingest-urls"
              className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              URLs <span className="text-gray-400">(one per line)</span>
            </label>
            <textarea
              id="ingest-urls"
              rows={5}
              value={urlsText}
              onChange={(e) => setUrlsText(e.target.value)}
              disabled={submitting}
              placeholder={"https://example.com/audio1.wav\nhttps://example.com/audio2.mp3"}
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 font-mono text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            />
          </div>

          <div>
            <label
              htmlFor="ingest-label"
              className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Label
            </label>
            <input
              id="ingest-label"
              type="text"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              disabled={submitting}
              placeholder="e.g. speech, noise, music"
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            />
          </div>

          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400">
              {error}
            </p>
          )}

          {/* Progress list */}
          {progress.length > 0 && (
            <div className="max-h-40 overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800">
              <ul className="divide-y divide-gray-200 dark:divide-gray-700">
                {progress.map((entry) => (
                  <li key={entry.url} className="flex items-start gap-2 px-3 py-2 text-xs">
                    <span
                      className={
                        entry.status === "success"
                          ? "mt-0.5 shrink-0 text-green-600"
                          : entry.status === "error"
                            ? "mt-0.5 shrink-0 text-red-600"
                            : "mt-0.5 shrink-0 text-gray-400"
                      }
                      aria-label={entry.status}
                    >
                      {entry.status === "success" ? "✓" : entry.status === "error" ? "✗" : "…"}
                    </span>
                    <span className="min-w-0 break-all text-gray-700 dark:text-gray-300">
                      {entry.url}
                      {entry.status === "error" && entry.message && (
                        <span className="ml-1 text-red-600 dark:text-red-400">— {entry.message}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Summary */}
          {summary && (
            <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm dark:border-green-800 dark:bg-green-900/20">
              <p className="font-semibold text-green-800 dark:text-green-300">Ingestion complete</p>
              <ul className="mt-1 space-y-0.5 text-green-700 dark:text-green-400">
                <li>Files: {summary.total_files}</li>
                <li>Duration: {summary.total_duration_seconds.toFixed(1)}s</li>
                <li>
                  Labels:{" "}
                  {Object.entries(summary.label_distribution)
                    .map(([k, v]) => `${k} (${v})`)
                    .join(", ") || "—"}
                </li>
              </ul>
            </div>
          )}

          {/* Footer buttons */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={handleClose}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              Close
            </button>
            {!summary && (
              <button
                type="submit"
                disabled={submitting || urlsText.trim() === ""}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? "Ingesting…" : "Start Ingestion"}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// IngestHFDialog
// ---------------------------------------------------------------------------

interface HFProgressEntry {
  filename: string;
  status: "pending" | "success" | "error";
  message?: string;
}

interface IngestHFDialogProps {
  onClose: () => void;
  onComplete: () => void;
}

function IngestHFDialog({ onClose, onComplete }: IngestHFDialogProps) {
  const [repoId, setRepoId] = React.useState("");
  const [split, setSplit] = React.useState("train");
  const [audioCol, setAudioCol] = React.useState("audio");
  const [labelCol, setLabelCol] = React.useState("");
  const [labelOverride, setLabelOverride] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [progress, setProgress] = React.useState<HFProgressEntry[]>([]);
  const [summary, setSummary] = React.useState<IngestSummary | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const esRef = React.useRef<EventSource | null>(null);

  // Clean up EventSource when dialog unmounts
  React.useEffect(() => {
    return () => {
      esRef.current?.close();
    };
  }, []);

  const handleClose = () => {
    esRef.current?.close();
    esRef.current = null;
    onClose();
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!repoId.trim()) {
      setError("Repository ID is required.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setProgress([]);
    setSummary(null);

    const body: Record<string, string> = {
      repo_id: repoId.trim(),
      split,
      audio_col: audioCol,
    };
    if (labelCol.trim()) body.label_col = labelCol.trim();
    if (labelOverride.trim()) body.label_override = labelOverride.trim();

    let jobId: string;
    try {
      const res = await fetch(apiUrl("/ingest/huggingface"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { job_id: string };
      jobId = data.job_id;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start ingestion job.");
      setSubmitting(false);
      return;
    }

    // Open SSE stream
    const es = new EventSource(apiUrl(`/ingest/huggingface/${jobId}/stream`));
    esRef.current = es;

    es.onmessage = (event) => {
      let parsed: {
        type: string;
        filename?: string;
        status?: string;
        message?: string;
        total_files?: number;
        total_duration_seconds?: number;
        label_distribution?: Record<string, number>;
      };
      try {
        parsed = JSON.parse(event.data) as typeof parsed;
      } catch {
        return;
      }

      // Backend sends type="progress" for per-sample updates
      if (parsed.type === "progress") {
        const { filename, status, message } = parsed;
        if (filename) {
          setProgress((prev) => {
            const existing = prev.find((e) => e.filename === filename);
            if (existing) {
              return prev.map((entry) =>
                entry.filename === filename
                  ? { ...entry, status: (status as "success" | "error") ?? "success", message }
                  : entry,
              );
            }
            return [
              ...prev,
              { filename, status: (status as "success" | "error") ?? "success", message },
            ];
          });
        }
      } else if (parsed.type === "summary") {
        setSummary({
          total_files: parsed.total_files ?? 0,
          total_duration_seconds: parsed.total_duration_seconds ?? 0,
          label_distribution: parsed.label_distribution ?? {},
        });
        es.close();
        esRef.current = null;
        setSubmitting(false);
        onComplete();
      }
    };

    es.onerror = () => {
      setError("Stream connection lost. The job may still be running in the background.");
      es.close();
      esRef.current = null;
      setSubmitting(false);
    };
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="ingest-hf-title"
    >
      <div className="w-full max-w-lg rounded-xl bg-white shadow-2xl dark:bg-gray-900">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4 dark:border-gray-700">
          <h2 id="ingest-hf-title" className="text-base font-semibold text-gray-900 dark:text-gray-100">
            Ingest from HuggingFace
          </h2>
          <button
            type="button"
            onClick={handleClose}
            className="rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600 dark:hover:bg-gray-800 dark:hover:text-gray-300"
            aria-label="Close dialog"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <form onSubmit={(e) => { void handleSubmit(e); }} className="space-y-4 px-6 py-4">
          {/* repo_id — required */}
          <div>
            <label
              htmlFor="hf-repo-id"
              className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Repository ID <span className="text-red-500">*</span>
            </label>
            <input
              id="hf-repo-id"
              type="text"
              value={repoId}
              onChange={(e) => setRepoId(e.target.value)}
              disabled={submitting}
              placeholder="e.g. mozilla-foundation/common_voice_11_0"
              className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
            />
          </div>

          {/* split + audio_col side by side */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="hf-split"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Split
              </label>
              <input
                id="hf-split"
                type="text"
                value={split}
                onChange={(e) => setSplit(e.target.value)}
                disabled={submitting}
                placeholder="train"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </div>
            <div>
              <label
                htmlFor="hf-audio-col"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Audio column
              </label>
              <input
                id="hf-audio-col"
                type="text"
                value={audioCol}
                onChange={(e) => setAudioCol(e.target.value)}
                disabled={submitting}
                placeholder="audio"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </div>
          </div>

          {/* label_col + label_override side by side */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label
                htmlFor="hf-label-col"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Label column <span className="text-gray-400">(optional)</span>
              </label>
              <input
                id="hf-label-col"
                type="text"
                value={labelCol}
                onChange={(e) => setLabelCol(e.target.value)}
                disabled={submitting}
                placeholder="e.g. sentence"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </div>
            <div>
              <label
                htmlFor="hf-label-override"
                className="mb-1 block text-sm font-medium text-gray-700 dark:text-gray-300"
              >
                Label override <span className="text-gray-400">(optional)</span>
              </label>
              <input
                id="hf-label-override"
                type="text"
                value={labelOverride}
                onChange={(e) => setLabelOverride(e.target.value)}
                disabled={submitting}
                placeholder="e.g. speech"
                className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:opacity-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100"
              />
            </div>
          </div>

          {error && (
            <p className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700 dark:bg-red-900/30 dark:text-red-400">
              {error}
            </p>
          )}

          {/* Progress list */}
          {progress.length > 0 && (
            <div className="max-h-40 overflow-y-auto rounded-lg border border-gray-200 bg-gray-50 dark:border-gray-700 dark:bg-gray-800">
              <ul className="divide-y divide-gray-200 dark:divide-gray-700">
                {progress.map((entry) => (
                  <li key={entry.filename} className="flex items-start gap-2 px-3 py-2 text-xs">
                    <span
                      className={
                        entry.status === "success"
                          ? "mt-0.5 shrink-0 text-green-600"
                          : entry.status === "error"
                            ? "mt-0.5 shrink-0 text-red-600"
                            : "mt-0.5 shrink-0 text-gray-400"
                      }
                      aria-label={entry.status}
                    >
                      {entry.status === "success" ? "✓" : entry.status === "error" ? "✗" : "…"}
                    </span>
                    <span className="min-w-0 break-all text-gray-700 dark:text-gray-300">
                      {entry.filename}
                      {entry.status === "error" && entry.message && (
                        <span className="ml-1 text-red-600 dark:text-red-400">— {entry.message}</span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Summary */}
          {summary && (
            <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm dark:border-green-800 dark:bg-green-900/20">
              <p className="font-semibold text-green-800 dark:text-green-300">Ingestion complete</p>
              <ul className="mt-1 space-y-0.5 text-green-700 dark:text-green-400">
                <li>Files: {summary.total_files}</li>
                <li>Duration: {summary.total_duration_seconds.toFixed(1)}s</li>
                <li>
                  Labels:{" "}
                  {Object.entries(summary.label_distribution)
                    .map(([k, v]) => `${k} (${v})`)
                    .join(", ") || "—"}
                </li>
              </ul>
            </div>
          )}

          {/* Footer buttons */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={handleClose}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:text-gray-300 dark:hover:bg-gray-800"
            >
              Close
            </button>
            {!summary && (
              <button
                type="submit"
                disabled={submitting || repoId.trim() === ""}
                className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {submitting ? "Ingesting…" : "Start Ingestion"}
              </button>
            )}
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DatasetBrowser
// ---------------------------------------------------------------------------

interface SampleRow {
  path: string;
  filename: string;
  split: string;
  label: string;
  duration_s: number;
  sample_rate: number;
  metadata: Record<string, unknown>;
}

interface SamplesResponse {
  items: SampleRow[];
  total: number;
  page: number;
  page_size: number;
}

interface DatasetBrowserProps {
  project: string;
  version: string;
}

function DatasetBrowser({ project, version }: DatasetBrowserProps) {
  const PAGE_SIZE = 50;
  const [page, setPage] = React.useState(1);
  const [labelFilter, setLabelFilter] = React.useState("");
  const [splitFilter, setSplitFilter] = React.useState("");
  const [expandedRows, setExpandedRows] = React.useState<Set<string>>(new Set());
  const [samples, setSamples] = React.useState<SampleRow[]>([]);
  const [totalPages, setTotalPages] = React.useState(1);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!project || !version) return;
    let cancelled = false;
    setLoading(true);
    setError(null);

    const query: Record<string, string | number> = { page, page_size: PAGE_SIZE };
    if (labelFilter) query.label = labelFilter;
    if (splitFilter) query.split = splitFilter;

    fetch(apiUrl(`/projects/${encodeURIComponent(project)}/versions/${encodeURIComponent(version)}/samples`, query))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<SamplesResponse>;
      })
      .then((data) => {
        if (cancelled) return;
        setSamples(data.items ?? []);
        setTotalPages(Math.max(1, Math.ceil(data.total / PAGE_SIZE)));
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Failed to load samples");
        setLoading(false);
      });

    return () => { cancelled = true; };
  }, [project, version, page, labelFilter, splitFilter]);

  // Reset to page 1 when filters change
  const handleLabelFilter = (val: string) => { setLabelFilter(val); setPage(1); };
  const handleSplitFilter = (val: string) => { setSplitFilter(val); setPage(1); };

  const toggleRow = (path: string) => {
    setExpandedRows((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  // Derive unique label/split values from current page for filter dropdowns
  const uniqueLabels = Array.from(new Set(samples.map((s) => s.label).filter(Boolean))).sort();
  const uniqueSplits = Array.from(new Set(samples.map((s) => s.split).filter(Boolean))).sort();

  return (
    <div className="rounded-2xl border border-secondary-200 bg-white dark:border-secondary-700 dark:bg-secondary-900 shadow-sm overflow-hidden">
      {/* Header + filter bar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-secondary-200 dark:border-secondary-700 px-5 py-3">
        <h3 className="text-sm font-bold text-secondary-900 dark:text-secondary-100 mr-auto">
          Sample Browser
        </h3>

        {/* Label filter */}
        <div className="flex items-center gap-1.5">
          <label htmlFor="db-label-filter" className="text-xs text-secondary-500 dark:text-secondary-400">
            Label
          </label>
          <select
            id="db-label-filter"
            value={labelFilter}
            onChange={(e) => handleLabelFilter(e.target.value)}
            className="rounded border border-secondary-300 dark:border-secondary-600 bg-white dark:bg-secondary-800 px-2 py-1 text-xs text-secondary-800 dark:text-secondary-200 focus:outline-none focus:ring-1 focus:ring-primary-500"
          >
            <option value="">All</option>
            {uniqueLabels.map((l) => <option key={l} value={l}>{l}</option>)}
          </select>
        </div>

        {/* Split filter */}
        <div className="flex items-center gap-1.5">
          <label htmlFor="db-split-filter" className="text-xs text-secondary-500 dark:text-secondary-400">
            Split
          </label>
          <select
            id="db-split-filter"
            value={splitFilter}
            onChange={(e) => handleSplitFilter(e.target.value)}
            className="rounded border border-secondary-300 dark:border-secondary-600 bg-white dark:bg-secondary-800 px-2 py-1 text-xs text-secondary-800 dark:text-secondary-200 focus:outline-none focus:ring-1 focus:ring-primary-500"
          >
            <option value="">All</option>
            {uniqueSplits.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      {/* Loading / error states */}
      {loading && (
        <div className="px-5 py-8 text-center text-sm text-secondary-500 dark:text-secondary-400">
          Loading samples…
        </div>
      )}
      {!loading && error && (
        <div className="px-5 py-4 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {/* Table */}
      {!loading && !error && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-secondary-200 dark:border-secondary-700 bg-secondary-50 dark:bg-secondary-800">
                <th className="text-left px-4 py-2 font-semibold text-secondary-600 dark:text-secondary-400 uppercase tracking-wide">Filename</th>
                <th className="text-left px-3 py-2 font-semibold text-secondary-600 dark:text-secondary-400 uppercase tracking-wide">Split</th>
                <th className="text-left px-3 py-2 font-semibold text-secondary-600 dark:text-secondary-400 uppercase tracking-wide">Label</th>
                <th className="text-right px-3 py-2 font-semibold text-secondary-600 dark:text-secondary-400 uppercase tracking-wide">Duration</th>
                <th className="text-right px-3 py-2 font-semibold text-secondary-600 dark:text-secondary-400 uppercase tracking-wide">Sample Rate</th>
                <th className="px-3 py-2 font-semibold text-secondary-600 dark:text-secondary-400 uppercase tracking-wide">Audio</th>
              </tr>
            </thead>
            <tbody>
              {samples.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-4 py-8 text-center text-secondary-400 dark:text-secondary-500">
                    No samples found.
                  </td>
                </tr>
              )}
              {samples.map((sample) => {
                const isExpanded = expandedRows.has(sample.path);
                const metaEntries = Object.entries(sample.metadata ?? {});
                return (
                  <React.Fragment key={sample.path}>
                    <tr
                      className="border-b border-secondary-100 dark:border-secondary-800 hover:bg-secondary-50 dark:hover:bg-secondary-800/50 cursor-pointer"
                      onClick={() => toggleRow(sample.path)}
                      aria-expanded={isExpanded}
                    >
                      <td className="px-4 py-2 font-medium text-secondary-800 dark:text-secondary-200 max-w-[200px] truncate" title={sample.filename}>
                        {sample.filename}
                      </td>
                      <td className="px-3 py-2 text-secondary-600 dark:text-secondary-400">{sample.split}</td>
                      <td className="px-3 py-2 text-secondary-600 dark:text-secondary-400">{sample.label}</td>
                      <td className="px-3 py-2 text-right tabular-nums text-secondary-600 dark:text-secondary-400">
                        {sample.duration_s.toFixed(1)}s
                      </td>
                      <td className="px-3 py-2 text-right tabular-nums text-secondary-600 dark:text-secondary-400">
                        {sample.sample_rate.toLocaleString()} Hz
                      </td>
                      <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                        {/* Audio player — captions not applicable for audio-only content */}
                        <audio
                          controls
                          src={apiUrl(`/files/${encodeURIComponent(project)}/${sample.path.split("/").map(encodeURIComponent).join("/")}`)}
                          className="h-7 w-44"
                          aria-label={`Audio for ${sample.filename}`}
                        />
                      </td>
                    </tr>
                    {isExpanded && (
                      <tr className="border-b border-secondary-100 dark:border-secondary-800 bg-secondary-50 dark:bg-secondary-800/30">
                        <td colSpan={6} className="px-6 py-3">
                          <p className="text-xs font-semibold text-secondary-600 dark:text-secondary-400 mb-2 uppercase tracking-wide">
                            Full Metadata
                          </p>
                          {metaEntries.length === 0 ? (
                            <p className="text-xs text-secondary-400 dark:text-secondary-500">No metadata fields.</p>
                          ) : (
                            <dl className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3 lg:grid-cols-4">
                              {metaEntries.map(([k, v]) => (
                                <div key={k} className="flex flex-col">
                                  <dt className="text-xs font-medium text-secondary-500 dark:text-secondary-400">{k}</dt>
                                  <dd className="text-xs text-secondary-800 dark:text-secondary-200 break-all">
                                    {typeof v === "object" ? JSON.stringify(v) : String(v)}
                                  </dd>
                                </div>
                              ))}
                            </dl>
                          )}
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {!loading && !error && (
        <div className="flex items-center justify-between border-t border-secondary-200 dark:border-secondary-700 px-5 py-3">
          <button
            type="button"
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded border border-secondary-300 dark:border-secondary-600 px-3 py-1 text-xs font-medium text-secondary-700 dark:text-secondary-300 hover:bg-secondary-50 dark:hover:bg-secondary-800 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-xs text-secondary-500 dark:text-secondary-400">
            Page {page} of {totalPages}
          </span>
          <button
            type="button"
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded border border-secondary-300 dark:border-secondary-600 px-3 py-1 text-xs font-medium text-secondary-700 dark:text-secondary-300 hover:bg-secondary-50 dark:hover:bg-secondary-800 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

function filterGeneratedRows(rows: AudioRow[], searchTerm: string) {
  const query = searchTerm.trim().toLowerCase();
  if (!query) return rows;
  return rows.filter((item) =>
    [item.label, item.split, item.path]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(query),
  );
}

function filterInputRows(rows: AudioRow[], searchTerm: string) {
  const query = searchTerm.trim().toLowerCase();
  if (!query) return rows;
  return rows.filter((item) =>
    [item.label, item.path]
      .filter(Boolean)
      .join(" ")
      .toLowerCase()
      .includes(query),
  );
}

interface DatasetManagerProps {
  activeProject: string | null;
}

export default function DatasetManager({ activeProject }: DatasetManagerProps) {
  const [datasetType, setDatasetType] = React.useState<DatasetMode>("generated");
  const [datasets, setDatasets] = React.useState<DatasetSummary[]>([]);
  const [inputLabels, setInputLabels] = React.useState<InputLabelSummary[]>([]);
  const [inputLabel, setInputLabel] = React.useState("");
  const [project, setProject] = React.useState(activeProject ?? "");
  const [version, setVersion] = React.useState("");

  // Keep project in sync with activeProject prop; reset version when project changes
  React.useEffect(() => {
    if (activeProject && activeProject !== project) {
      setProject(activeProject);
      setVersion(""); // reset version — will be filled by sources effect
    }
  }, [activeProject]); // eslint-disable-line react-hooks/exhaustive-deps
  const [searchTerm, setSearchTerm] = React.useState("");
  const [generatedData, setGeneratedData] = React.useState<AudioRow[]>([]);
  const [inputData, setInputData] = React.useState<AudioRow[]>([]);
  // null = loading, DatasetSummary[] = loaded
  const [sourcesLoading, setSourcesLoading] = React.useState<boolean>(false);
  // Incrementing this triggers the sources effect to re-run
  const [sourcesRefreshKey, setSourcesRefreshKey] = React.useState(0);
  const datasetRequestSeq = React.useRef(0);
  const [showIngestURL, setShowIngestURL] = React.useState(false);
  const [showIngestHF, setShowIngestHF] = React.useState(false);

  // Fetch both dataset lists whenever sourcesRefreshKey changes
  React.useEffect(() => {
    let cancelled = false;
    Promise.all([
      fetch(apiUrl("/datasets")).then((r) => r.json() as Promise<DatasetSummary[]>),
      fetch(apiUrl("/input-datasets")).then((r) => r.json() as Promise<InputLabelSummary[]>),
    ])
      .then(([gen, inp]) => {
        if (cancelled) return;
        setDatasets(gen);
        if (gen.length > 0) {
          // Prefer activeProject if it exists in the list, otherwise first
          const preferred = activeProject && gen.find((d) => d.project === activeProject);
          const defaultProject = preferred ? preferred.project : gen[0].project;
          setProject((prev) => prev || defaultProject);
          setVersion((prev) => {
            if (prev) return prev;
            const match = gen.find((d) => d.project === (prev || defaultProject));
            return match?.versions[0] ?? gen[0].versions[0] ?? "";
          });
        }
        setInputLabels(inp);
        if (inp.length > 0) {
          setInputLabel((prev) => prev || inp[0].label);
        }
        setSourcesLoading(false);
      })
      .catch(() => {
        if (!cancelled) setSourcesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sourcesRefreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleRefresh = () => {
    setSourcesLoading(true);
    setSourcesRefreshKey((k) => k + 1);
  };

  React.useEffect(() => {
    if (datasetType !== "generated") return;
    if (!project || !version) return;

    const requestId = ++datasetRequestSeq.current;
    const controller = new AbortController();
    fetch(apiUrl("/dataset", { project, version }), { signal: controller.signal })
      .then((res) => res.json() as Promise<AudioRow[]>)
      .then((rows) => {
        if (requestId === datasetRequestSeq.current && datasetType === "generated") {
          setGeneratedData(rows);
        }
      })
      .catch((err) => {
        if (err?.name !== "AbortError") console.error("Failed to load generated dataset", err);
      });
    return () => controller.abort();
  }, [datasetType, project, version]);

  React.useEffect(() => {
    if (datasetType !== "input") return;

    const requestId = ++datasetRequestSeq.current;
    const controller = new AbortController();
    fetch(apiUrl("/input-dataset", { label: inputLabel }), { signal: controller.signal })
      .then((res) => res.json() as Promise<AudioRow[]>)
      .then((rows) => {
        if (requestId === datasetRequestSeq.current && datasetType === "input") {
          setInputData(rows);
        }
      })
      .catch((err) => {
        if (err?.name !== "AbortError") console.error("Failed to load input dataset", err);
      });
    return () => controller.abort();
  }, [datasetType, inputLabel]);

  const currentVersions = datasets.find((d) => d.project === project)?.versions ?? [];

  const filteredGenerated = React.useMemo(
    () => filterGeneratedRows(generatedData, searchTerm),
    [generatedData, searchTerm],
  );
  const filteredInput = React.useMemo(
    () => filterInputRows(inputData, searchTerm),
    [inputData, searchTerm],
  );
  const generatedGroups = React.useMemo(
    () => groupGeneratedRows(filteredGenerated),
    [filteredGenerated],
  );
  const inputGroups = React.useMemo(
    () => groupInputRows(filteredInput),
    [filteredInput],
  );

  const activeData = datasetType === "generated" ? filteredGenerated : filteredInput;
  const hasLoadedSources =
    datasetType === "generated" ? datasets.length > 0 : inputLabels.length > 0;
  const activeRootPath =
    datasetType === "generated"
      ? `workspace/datasets/output/${project || "project"}/${version || "version"}`
      : `workspace/datasets/input/${inputLabel || "label"}`;
  const activeSummary =
    datasetType === "generated"
      ? `${datasets.length} project${datasets.length === 1 ? "" : "s"}`
      : `${inputLabels.length} label${inputLabels.length === 1 ? "" : "s"}`;

  return (
    <>
      <div className="flex-1 overflow-auto bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.12),_transparent_32%),linear-gradient(180deg,_#f8fafc_0%,_#ffffff_45%,_#f8fafc_100%)] p-4 dark:bg-[radial-gradient(circle_at_top_left,_rgba(59,130,246,0.18),_transparent_30%),linear-gradient(180deg,_#0f172a_0%,_#111827_45%,_#020617_100%)] sm:p-6">
      <div className="mx-auto max-w-7xl space-y-6">
        <DatasetHeader
          datasetType={datasetType}
          datasets={datasets}
          inputLabels={inputLabels}
          activeDataCount={activeData.length}
          activeRootPath={activeRootPath}
          activeSummary={activeSummary}
          onDatasetTypeChange={setDatasetType}
          onRefresh={handleRefresh}
          isRefreshing={sourcesLoading}
          onIngestURL={() => setShowIngestURL(true)}
          onIngestHF={() => setShowIngestHF(true)}
        />

        <section className="grid gap-6 xl:grid-cols-[320px_minmax(0,1fr)]">
          <DatasetSidebar
            datasetType={datasetType}
            datasets={datasets}
            inputLabels={inputLabels}
            project={project}
            version={version}
            inputLabel={inputLabel}
            searchTerm={searchTerm}
            currentVersions={currentVersions}
            activeRootPath={activeRootPath}
            onProjectChange={(nextProject) => {
              setProject(nextProject);
              const nextVersion =
                datasets.find((d) => d.project === nextProject)?.versions[0] ?? "";
              setVersion(nextVersion);
            }}
            onVersionChange={setVersion}
            onInputLabelChange={setInputLabel}
            onSearchTermChange={setSearchTerm}
          />

          <main className="space-y-6">
            {datasetType === "generated" && project && version && (
              <DatasetStats project={project} version={version} />
            )}
            {datasetType === "generated" && project && version && (
              <DatasetBrowser project={project} version={version} />
            )}
            <DatasetResults
              datasetType={datasetType}
              project={project}
              version={version}
              inputLabel={inputLabel}
              generatedGroups={generatedGroups}
              inputGroups={inputGroups}
              activeDataCount={activeData.length}
              hasLoadedSources={hasLoadedSources}
            />
          </main>
        </section>
      </div>
    </div>
    {showIngestURL && (
      <IngestURLDialog
        onClose={() => setShowIngestURL(false)}
        onComplete={() => {
          setShowIngestURL(false);
          handleRefresh();
        }}
      />
    )}
    {showIngestHF && (
      <IngestHFDialog
        onClose={() => setShowIngestHF(false)}
        onComplete={() => {
          setShowIngestHF(false);
          handleRefresh();
        }}
      />
    )}
    </>
  );
}

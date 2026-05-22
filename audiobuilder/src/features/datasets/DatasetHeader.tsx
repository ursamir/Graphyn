import { Database, Download, RefreshCw } from "lucide-react";
import React from "react";
import type { DatasetMode, DatasetSummary, InputLabelSummary } from "./types";

interface DatasetHeaderProps {
  datasetType: DatasetMode;
  datasets: DatasetSummary[];
  inputLabels: InputLabelSummary[];
  activeDataCount: number;
  activeRootPath: string;
  activeSummary: string;
  onDatasetTypeChange: (value: DatasetMode) => void;
  onRefresh: () => void;
  isRefreshing?: boolean;
  onIngestURL?: () => void;
  onIngestHF?: () => void;
}

export default function DatasetHeader({
  datasetType,
  datasets,
  inputLabels,
  activeDataCount,
  activeRootPath,
  activeSummary,
  onDatasetTypeChange,
  onRefresh,
  isRefreshing = false,
  onIngestURL,
  onIngestHF,
}: DatasetHeaderProps) {
  const [ingestOpen, setIngestOpen] = React.useState(false);
  const ingestRef = React.useRef<HTMLDivElement>(null);

  // Close popover when clicking outside
  React.useEffect(() => {
    if (!ingestOpen) return;
    function handleClickOutside(e: MouseEvent) {
      if (ingestRef.current && !ingestRef.current.contains(e.target as Node)) {
        setIngestOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [ingestOpen]);

  return (
    <section className="overflow-hidden rounded-3xl border border-secondary-200/80 bg-white/85 shadow-xl backdrop-blur dark:border-secondary-800 dark:bg-secondary-900/75">
      <div className="grid gap-6 px-5 py-6 sm:px-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(280px,0.8fr)] lg:px-8 lg:py-8">
        <div>
          <div className="inline-flex items-center gap-2 rounded-full border border-primary-200 bg-primary-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-primary-700 dark:border-primary-900/60 dark:bg-primary-900/30 dark:text-primary-200">
            <Database className="h-3.5 w-3.5" />
            Dataset Manager
          </div>
          <h2 className="mt-4 text-3xl font-bold tracking-tight text-secondary-950 dark:text-secondary-50 sm:text-4xl">
            Organized audio libraries, not an endless file wall.
          </h2>
          <p className="mt-3 max-w-3xl text-sm leading-6 text-secondary-600 dark:text-secondary-300 sm:text-base">
            Browse exported datasets by project, version, and split, or inspect
            raw input captures by label. Each folder is summarized first, with
            only a few preview players shown until you expand it.
          </p>

          <div className="mt-6 flex flex-wrap gap-2">
            <button
              type="button"
              onClick={() => onDatasetTypeChange("generated")}
              className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition-all ${
                datasetType === "generated"
                  ? "bg-primary-600 text-white shadow-md shadow-primary-600/25"
                  : "bg-secondary-100 text-secondary-700 hover:bg-secondary-200 dark:bg-secondary-800 dark:text-secondary-200 dark:hover:bg-secondary-700"
              }`}
            >
              Exported datasets
            </button>
            <button
              type="button"
              onClick={() => onDatasetTypeChange("input")}
              className={`inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold transition-all ${
                datasetType === "input"
                  ? "bg-primary-600 text-white shadow-md shadow-primary-600/25"
                  : "bg-secondary-100 text-secondary-700 hover:bg-secondary-200 dark:bg-secondary-800 dark:text-secondary-200 dark:hover:bg-secondary-700"
              }`}
            >
              Input captures
            </button>
            <button
              type="button"
              onClick={onRefresh}
              disabled={isRefreshing}
              className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold bg-secondary-100 text-secondary-700 hover:bg-secondary-200 dark:bg-secondary-800 dark:text-secondary-200 dark:hover:bg-secondary-700 disabled:opacity-50 transition-all"
              title="Refresh datasets"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${isRefreshing ? "animate-spin" : ""}`} />
              Refresh
            </button>

            {/* Ingest button with popover */}
            <div ref={ingestRef} className="relative">
              <button
                type="button"
                onClick={() => setIngestOpen((o) => !o)}
                className="inline-flex items-center gap-2 rounded-full px-4 py-2 text-sm font-semibold bg-secondary-100 text-secondary-700 hover:bg-secondary-200 dark:bg-secondary-800 dark:text-secondary-200 dark:hover:bg-secondary-700 transition-all"
                title="Ingest audio data"
              >
                <Download className="h-3.5 w-3.5" />
                Ingest
              </button>

              {ingestOpen && (
                <div className="absolute left-0 top-full z-20 mt-2 w-48 overflow-hidden rounded-xl border border-secondary-200 bg-white shadow-lg dark:border-secondary-700 dark:bg-secondary-900">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-secondary-700 hover:bg-secondary-50 dark:text-secondary-200 dark:hover:bg-secondary-800"
                    onClick={() => {
                      setIngestOpen(false);
                      onIngestURL?.();
                    }}
                  >
                    From URL
                  </button>
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 px-4 py-2.5 text-sm text-secondary-700 hover:bg-secondary-50 dark:text-secondary-200 dark:hover:bg-secondary-800"
                    onClick={() => {
                      setIngestOpen(false);
                      onIngestHF?.();
                    }}
                  >
                    From HuggingFace
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:gap-4">
          <div className="rounded-2xl border border-secondary-200 bg-secondary-50/80 p-4 dark:border-secondary-700 dark:bg-secondary-950/60">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-secondary-500">
              {datasetType === "generated" ? "Projects" : "Labels"}
            </div>
            <div className="mt-2 text-3xl font-bold text-secondary-950 dark:text-secondary-50">
              {datasetType === "generated" ? datasets.length : inputLabels.length}
            </div>
            <p className="mt-1 text-xs text-secondary-500 dark:text-secondary-400">
              {datasetType === "generated"
                ? "Available export namespaces"
                : "Available input folders"}
            </p>
          </div>
          <div className="rounded-2xl border border-secondary-200 bg-secondary-50/80 p-4 dark:border-secondary-700 dark:bg-secondary-950/60">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-secondary-500">
              Files
            </div>
            <div className="mt-2 text-3xl font-bold text-secondary-950 dark:text-secondary-50">
              {activeDataCount}
            </div>
            <p className="mt-1 text-xs text-secondary-500 dark:text-secondary-400">
              {datasetType === "generated"
                ? "Visible in the selected dataset"
                : "Visible in the selected label"}
            </p>
          </div>
          <div className="rounded-2xl border border-secondary-200 bg-secondary-50/80 p-4 dark:border-secondary-700 dark:bg-secondary-950/60">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-secondary-500">
              Root folder
            </div>
            <div className="mt-2 break-all text-sm font-semibold text-secondary-950 dark:text-secondary-50">
              {activeRootPath}
            </div>
            <p className="mt-1 text-xs text-secondary-500 dark:text-secondary-400">
              Clear folder context for the selected source
            </p>
          </div>
          <div className="rounded-2xl border border-secondary-200 bg-secondary-50/80 p-4 dark:border-secondary-700 dark:bg-secondary-950/60">
            <div className="text-[11px] font-semibold uppercase tracking-[0.2em] text-secondary-500">
              Scope
            </div>
            <div className="mt-2 text-sm font-semibold text-secondary-950 dark:text-secondary-50">
              {activeSummary}
            </div>
            <p className="mt-1 text-xs text-secondary-500 dark:text-secondary-400">
              {datasetType === "generated"
                ? "Project and version selection"
                : "Input label selection"}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

import React from "react";
import {
  Play,
  Pause,
  Square,
  ChevronLeft,
  ChevronRight,
  Search,
  Tag,
  CheckCircle2,
  Circle,
  AlertCircle,
  RefreshCw,
  Mic,
  Download,
  Upload,
  ShieldCheck,
} from "lucide-react";
import { apiUrl } from "../../utils/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Project {
  name: string;
  status: string;
  versions: string[];
}

interface TaxonomyNode {
  name: string;
  description?: string;
  children: TaxonomyNode[];
}

interface Sample {
  path: string;
  filename: string;
  label?: string;
  duration_ms?: number;
}

interface Annotation {
  sample_path: string;
  label: string;
  start_ms?: number | null;
  end_ms?: number | null;
  annotator?: string;
}

type AnnotationStatus = "unannotated" | "partial" | "complete";
type FilterMode = "all" | "unannotated" | "partial";

interface ValidationResult {
  total_samples: number;
  annotated_count: number;
  unannotated_count: number;
  missing_labels: string[];
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function flattenTaxonomy(nodes: TaxonomyNode[], depth = 0): { label: string; depth: number }[] {
  const result: { label: string; depth: number }[] = [];
  for (const node of nodes) {
    result.push({ label: node.name, depth });
    if (node.children?.length) {
      result.push(...flattenTaxonomy(node.children, depth + 1));
    }
  }
  return result;
}

function getAnnotationStatus(
  samplePath: string,
  annotations: Annotation[],
): AnnotationStatus {
  const sampleAnnotations = annotations.filter((a) => a.sample_path === samplePath);
  if (sampleAnnotations.length === 0) return "unannotated";
  const hasWholeFile = sampleAnnotations.some((a) => a.start_ms == null && a.end_ms == null);
  if (hasWholeFile) return "complete";
  return "partial";
}

function StatusIcon({ status }: { status: AnnotationStatus }) {
  if (status === "complete")
    return <CheckCircle2 className="h-4 w-4 text-green-500 flex-shrink-0" />;
  if (status === "partial")
    return <AlertCircle className="h-4 w-4 text-amber-500 flex-shrink-0" />;
  return <Circle className="h-4 w-4 text-secondary-400 flex-shrink-0" />;
}

// ---------------------------------------------------------------------------
// Debounce hook
// ---------------------------------------------------------------------------

function useDebounce<T>(value: T, delay: number): T {
  const [debounced, setDebounced] = React.useState(value);
  React.useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return debounced;
}

// ---------------------------------------------------------------------------
// WaveformPlayer component
// ---------------------------------------------------------------------------

interface WaveformPlayerProps {
  audioUrl: string | null;
  annotations: Annotation[];
  taxonomy: { label: string; depth: number }[];
  onRegionCreated: (start_ms: number, end_ms: number, label: string) => void;
  isPlaying: boolean;
  onPlayPause: () => void;
  onStop: () => void;
  wsRef: React.MutableRefObject<WaveSurferInstance | null>;
}

// Minimal WaveSurfer type stubs (avoids needing @types/wavesurfer.js)
interface WaveSurferInstance {
  destroy(): void;
  load(url: string): void;
  play(): void;
  pause(): void;
  stop(): void;
  isPlaying(): boolean;
  on(event: string, cb: (...args: unknown[]) => void): void;
  getDuration(): number;
  getCurrentTime(): number;
  seekTo(progress: number): void;
}

interface RegionsPluginInstance {
  addRegion(opts: { start: number; end: number; color: string; drag: boolean; resize: boolean }): RegionInstance;
  clearRegions(): void;
  on(event: string, cb: (...args: unknown[]) => void): void;
}

interface RegionInstance {
  id: string;
  start: number;
  end: number;
  remove(): void;
}

const REGION_COLORS = [
  "rgba(59,130,246,0.3)",
  "rgba(16,185,129,0.3)",
  "rgba(245,158,11,0.3)",
  "rgba(239,68,68,0.3)",
  "rgba(139,92,246,0.3)",
  "rgba(236,72,153,0.3)",
  "rgba(20,184,166,0.3)",
  "rgba(249,115,22,0.3)",
  "rgba(132,204,22,0.3)",
];

function WaveformPlayer({
  audioUrl,
  annotations,
  taxonomy,
  onRegionCreated,
  isPlaying,
  onPlayPause,
  onStop,
  wsRef,
}: WaveformPlayerProps) {
  const containerRef = React.useRef<HTMLDivElement>(null);
  const regionsRef = React.useRef<RegionsPluginInstance | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [loaded, setLoaded] = React.useState(false);
  const [pendingRegion, setPendingRegion] = React.useState<{ start_ms: number; end_ms: number } | null>(null);
  const [pendingLabel, setPendingLabel] = React.useState("");
  const [currentTime, setCurrentTime] = React.useState(0);
  const [duration, setDuration] = React.useState(0);

  // Initialize WaveSurfer
  React.useEffect(() => {
    if (!containerRef.current) return;

    let ws: WaveSurferInstance | null = null;
    let regions: RegionsPluginInstance | null = null;

    const init = async () => {
      try {
        // Dynamic import to handle graceful failure if not installed
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const wsModule = await import(/* @vite-ignore */ "wavesurfer.js" as string) as any;
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const regModule = await import(/* @vite-ignore */ "wavesurfer.js/dist/plugins/regions.esm.js" as string) as any;
        const WaveSurfer = (wsModule.default ?? wsModule) as {
          create(opts: Record<string, unknown>): WaveSurferInstance;
        };
        const RegionsPlugin = (regModule.default ?? regModule) as {
          create(): RegionsPluginInstance;
        };

        regions = RegionsPlugin.create();
        regionsRef.current = regions;

        ws = WaveSurfer.create({
          container: containerRef.current!,
          waveColor: "#6366f1",
          progressColor: "#4f46e5",
          cursorColor: "#e11d48",
          height: 100,
          normalize: true,
          plugins: [regions],
        });

        wsRef.current = ws;

        ws.on("ready", () => {
          setLoaded(true);
          setDuration(ws!.getDuration());
          setError(null);
          // Draw existing time-range annotations as regions
          regions!.clearRegions();
          annotations
            .filter((a) => a.start_ms != null && a.end_ms != null)
            .forEach((a, i) => {
              regions!.addRegion({
                start: (a.start_ms ?? 0) / 1000,
                end: (a.end_ms ?? 0) / 1000,
                color: REGION_COLORS[i % REGION_COLORS.length],
                drag: false,
                resize: false,
              });
            });
        });

        ws.on("error", (err: unknown) => {
          setError(`Waveform load error: ${String(err)}`);
          setLoaded(false);
        });

        ws.on("audioprocess", () => {
          setCurrentTime(ws!.getCurrentTime());
        });

        ws.on("seek", () => {
          setCurrentTime(ws!.getCurrentTime());
        });

        // Region creation: user drags on waveform
        regions.on("region-created", (region: unknown) => {
          const r = region as RegionInstance;
          setPendingRegion({
            start_ms: Math.round(r.start * 1000),
            end_ms: Math.round(r.end * 1000),
          });
          setPendingLabel(taxonomy[0]?.label ?? "");
        });
      } catch (e) {
        setError(`Failed to load wavesurfer.js: ${e instanceof Error ? e.message : String(e)}`);
      }
    };

    void init();

    return () => {
      ws?.destroy();
      wsRef.current = null;
      regionsRef.current = null;
      setLoaded(false);
      setCurrentTime(0);
      setDuration(0);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load audio when URL changes
  React.useEffect(() => {
    if (!wsRef.current || !audioUrl) return;
    setLoaded(false);
    setError(null);
    setCurrentTime(0);
    setDuration(0);
    try {
      wsRef.current.load(audioUrl);
    } catch (e) {
      setError(`Load error: ${e instanceof Error ? e.message : String(e)}`);
    }
  }, [audioUrl, wsRef]);

  // Sync regions when annotations change
  React.useEffect(() => {
    if (!regionsRef.current || !loaded) return;
    regionsRef.current.clearRegions();
    annotations
      .filter((a) => a.start_ms != null && a.end_ms != null)
      .forEach((a, i) => {
        regionsRef.current!.addRegion({
          start: (a.start_ms ?? 0) / 1000,
          end: (a.end_ms ?? 0) / 1000,
          color: REGION_COLORS[i % REGION_COLORS.length],
          drag: false,
          resize: false,
        });
      });
  }, [annotations, loaded]);

  const formatTime = (s: number) => {
    const m = Math.floor(s / 60);
    const sec = Math.floor(s % 60);
    return `${m}:${sec.toString().padStart(2, "0")}`;
  };

  const handleConfirmRegion = () => {
    if (!pendingRegion || !pendingLabel) return;
    onRegionCreated(pendingRegion.start_ms, pendingRegion.end_ms, pendingLabel);
    setPendingRegion(null);
    setPendingLabel("");
  };

  const handleCancelRegion = () => {
    setPendingRegion(null);
    setPendingLabel("");
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Waveform container */}
      <div
        className="relative rounded-lg border border-secondary-200 bg-secondary-50 dark:border-secondary-700 dark:bg-secondary-800 overflow-hidden"
        style={{ minHeight: 120 }}
      >
        {!audioUrl && (
          <div className="absolute inset-0 flex items-center justify-center text-secondary-400 text-sm">
            <Mic className="h-5 w-5 mr-2" />
            Select a sample to view waveform
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center text-red-500 text-sm px-4 text-center">
            {error}
          </div>
        )}
        {audioUrl && !loaded && !error && (
          <div className="absolute inset-0 flex items-center justify-center text-secondary-400 text-sm">
            <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary-500 border-t-transparent mr-2" />
            Loading waveform…
          </div>
        )}
        <div ref={containerRef} className={audioUrl ? "p-2" : "hidden"} />
      </div>

      {/* Time display */}
      {loaded && (
        <div className="flex items-center justify-between text-xs text-secondary-500 dark:text-secondary-400 px-1">
          <span>{formatTime(currentTime)}</span>
          <span>{formatTime(duration)}</span>
        </div>
      )}

      {/* Playback controls */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onPlayPause}
          disabled={!loaded}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
          aria-label={isPlaying ? "Pause" : "Play"}
        >
          {isPlaying ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          {isPlaying ? "Pause" : "Play"}
        </button>
        <button
          type="button"
          onClick={onStop}
          disabled={!loaded}
          className="inline-flex items-center gap-1.5 rounded-lg border border-secondary-300 bg-white px-4 py-2 text-sm font-semibold text-secondary-700 hover:bg-secondary-50 disabled:opacity-50 transition-colors dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          aria-label="Stop"
        >
          <Square className="h-4 w-4" />
          Stop
        </button>
        {loaded && (
          <span className="ml-auto text-xs text-secondary-400">
            Click and drag on waveform to create a time-range annotation
          </span>
        )}
      </div>

      {/* Pending region label picker */}
      {pendingRegion && (
        <div className="rounded-lg border border-primary-300 bg-primary-50 p-3 dark:border-primary-700 dark:bg-primary-900/20">
          <p className="mb-2 text-sm font-semibold text-primary-800 dark:text-primary-200">
            New region: {(pendingRegion.start_ms / 1000).toFixed(2)}s –{" "}
            {(pendingRegion.end_ms / 1000).toFixed(2)}s
          </p>
          <div className="flex items-center gap-2">
            <select
              value={pendingLabel}
              onChange={(e) => setPendingLabel(e.target.value)}
              className="flex-1 rounded-md border border-secondary-300 bg-white px-2 py-1.5 text-sm dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            >
              {taxonomy.length > 0 ? (
                taxonomy.map(({ label, depth }) => (
                  <option key={label} value={label}>
                    {"  ".repeat(depth)}{label}
                  </option>
                ))
              ) : (
                <option value="">No taxonomy — type a label</option>
              )}
            </select>
            {taxonomy.length === 0 && (
              <input
                type="text"
                value={pendingLabel}
                onChange={(e) => setPendingLabel(e.target.value)}
                placeholder="Label"
                className="flex-1 rounded-md border border-secondary-300 bg-white px-2 py-1.5 text-sm dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
              />
            )}
            <button
              type="button"
              onClick={handleConfirmRegion}
              disabled={!pendingLabel}
              className="rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-700 disabled:opacity-50"
            >
              Add
            </button>
            <button
              type="button"
              onClick={handleCancelRegion}
              className="rounded-lg border border-secondary-300 bg-white px-3 py-1.5 text-xs font-semibold text-secondary-700 hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main AnnotationUI component
// ---------------------------------------------------------------------------

export default function AnnotationUI({ activeProject }: { activeProject?: string | null }) {
  // Project selection
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = React.useState<string>("");
  const [projectsLoading, setProjectsLoading] = React.useState(false);

  // Taxonomy
  const [taxonomy, setTaxonomy] = React.useState<{ label: string; depth: number }[]>([]);

  // Samples
  const [samples, setSamples] = React.useState<Sample[]>([]);
  const [samplesLoading, setSamplesLoading] = React.useState(false);

  // Annotations
  const [annotations, setAnnotations] = React.useState<Annotation[]>([]);

  // Selected sample
  const [selectedIndex, setSelectedIndex] = React.useState<number>(-1);

  // Filter / search
  const [filterMode, setFilterMode] = React.useState<FilterMode>("all");
  const [searchQuery, setSearchQuery] = React.useState("");

  // Whole-file label
  const [wholeFileLabel, setWholeFileLabel] = React.useState("");
  const [freeTextLabel, setFreeTextLabel] = React.useState("");

  // Playback state
  const [isPlaying, setIsPlaying] = React.useState(false);
  const wsRef = React.useRef<WaveSurferInstance | null>(null);

  // Auto-save queue
  const [pendingSave, setPendingSave] = React.useState<Annotation[] | null>(null);
  const debouncedPendingSave = useDebounce(pendingSave, 2000);

  // Status message
  const [statusMsg, setStatusMsg] = React.useState<string | null>(null);

  // Validation result (task 17.3)
  const [validationResult, setValidationResult] = React.useState<ValidationResult | null>(null);
  const [validating, setValidating] = React.useState(false);

  // Bulk mode (task 17.4)
  const [bulkMode, setBulkMode] = React.useState(false);
  const [selectedPaths, setSelectedPaths] = React.useState<Set<string>>(new Set());
  const [bulkLabel, setBulkLabel] = React.useState("");

  // Import file ref (task 17.2)
  const importFileRef = React.useRef<HTMLInputElement>(null);

  // ---------------------------------------------------------------------------
  // Load projects on mount
  // ---------------------------------------------------------------------------
  React.useEffect(() => {
    setProjectsLoading(true);
    fetch(apiUrl("/projects"))
      .then((r) => r.json())
      .then((data: Project[]) => {
        setProjects(data);
        if (data.length > 0) setSelectedProject(data[0].name);
      })
      .catch(() => setProjects([]))
      .finally(() => setProjectsLoading(false));
  }, []);

  // ---------------------------------------------------------------------------
  // Task 17.1: Sync activeProject prop → selectedProject state
  // ---------------------------------------------------------------------------
  React.useEffect(() => {
    if (activeProject) setSelectedProject(activeProject);
  }, [activeProject]);

  // ---------------------------------------------------------------------------
  // Load taxonomy + samples when project changes
  // ---------------------------------------------------------------------------
  React.useEffect(() => {
    if (!selectedProject) return;

    // Fetch taxonomy
    fetch(apiUrl(`/projects/${encodeURIComponent(selectedProject)}/taxonomy`))
      .then((r) => r.json())
      .then((tree: TaxonomyNode[]) => setTaxonomy(flattenTaxonomy(tree)))
      .catch(() => setTaxonomy([]));

    // Fetch annotations
    fetch(apiUrl(`/projects/${encodeURIComponent(selectedProject)}/annotations`))
      .then((r) => r.json())
      .then((data: Annotation[]) => setAnnotations(Array.isArray(data) ? data : []))
      .catch(() => setAnnotations([]));

    // Fetch samples — try versions endpoint first, fall back to input-datasets
    const project = projects.find((p) => p.name === selectedProject);
    const version = project?.versions?.[project.versions.length - 1];

    if (version) {
      setSamplesLoading(true);
      fetch(
        apiUrl(
          `/projects/${encodeURIComponent(selectedProject)}/versions/${encodeURIComponent(version)}/samples`,
        ),
      )
        .then((r) => r.json())
        .then((data: { samples?: Sample[]; items?: Sample[] } | Sample[]) => {
          const list = Array.isArray(data)
            ? data
            : (data.samples ?? data.items ?? []);
          setSamples(
            list.map((s) => ({
              ...s,
              filename: s.filename ?? s.path?.split("/").pop() ?? s.path,
            })),
          );
        })
        .catch(() => setSamples([]))
        .finally(() => setSamplesLoading(false));
    } else {
      // Fallback: use input-datasets
      setSamplesLoading(true);
      fetch(apiUrl("/input-datasets"))
        .then((r) => r.json())
        .then(
          (
            data: Record<
              string,
              { files: Array<{ path: string; filename?: string }> }
            >,
          ) => {
            const all: Sample[] = [];
            for (const [, ds] of Object.entries(data)) {
              for (const f of ds.files ?? []) {
                all.push({
                  path: f.path,
                  filename: f.filename ?? f.path.split("/").pop() ?? f.path,
                });
              }
            }
            setSamples(all);
          },
        )
        .catch(() => setSamples([]))
        .finally(() => setSamplesLoading(false));
    }

    setSelectedIndex(-1);
    setIsPlaying(false);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedProject]);

  // ---------------------------------------------------------------------------
  // Auto-save: debounced POST
  // ---------------------------------------------------------------------------
  React.useEffect(() => {
    if (!debouncedPendingSave || !selectedProject) return;
    fetch(apiUrl(`/projects/${encodeURIComponent(selectedProject)}/annotations`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(debouncedPendingSave),
    })
      .then(() => setStatusMsg("Saved"))
      .catch(() => setStatusMsg("Save failed"))
      .finally(() => {
        setTimeout(() => setStatusMsg(null), 2000);
        setPendingSave(null);
      });
  }, [debouncedPendingSave, selectedProject]);

  // ---------------------------------------------------------------------------
  // Filtered sample list
  // ---------------------------------------------------------------------------
  const filteredSamples = React.useMemo(() => {
    return samples.filter((s) => {
      const status = getAnnotationStatus(s.path, annotations);
      if (filterMode === "unannotated" && status !== "unannotated") return false;
      if (filterMode === "partial" && status !== "partial") return false;
      if (
        searchQuery &&
        !s.filename.toLowerCase().includes(searchQuery.toLowerCase())
      )
        return false;
      return true;
    });
  }, [samples, annotations, filterMode, searchQuery]);

  // ---------------------------------------------------------------------------
  // Selected sample
  // ---------------------------------------------------------------------------
  const selectedSample = selectedIndex >= 0 ? filteredSamples[selectedIndex] : null;

  const selectedAnnotations = React.useMemo(
    () =>
      selectedSample
        ? annotations.filter((a) => a.sample_path === selectedSample.path)
        : [],
    [selectedSample, annotations],
  );

  // Audio URL for selected sample
  const audioUrl = selectedSample
    ? apiUrl(`/files/${encodeURIComponent(selectedSample.path)}`)
    : null;

  // ---------------------------------------------------------------------------
  // Progress indicator
  // ---------------------------------------------------------------------------
  const annotatedCount = React.useMemo(
    () =>
      samples.filter(
        (s) => getAnnotationStatus(s.path, annotations) !== "unannotated",
      ).length,
    [samples, annotations],
  );

  // ---------------------------------------------------------------------------
  // Annotation helpers
  // ---------------------------------------------------------------------------
  const addAnnotation = React.useCallback(
    (ann: Annotation) => {
      setAnnotations((prev) => {
        // For whole-file: replace existing whole-file annotation for same path
        if (ann.start_ms == null && ann.end_ms == null) {
          const filtered = prev.filter(
            (a) =>
              !(
                a.sample_path === ann.sample_path &&
                a.start_ms == null &&
                a.end_ms == null
              ),
          );
          const next = [...filtered, ann];
          setPendingSave(next);
          return next;
        }
        const next = [...prev, ann];
        setPendingSave(next);
        return next;
      });
    },
    [],
  );

  const handleWholeFileLabel = () => {
    if (!selectedSample) return;
    const label = taxonomy.length > 0 ? wholeFileLabel : freeTextLabel;
    if (!label) return;
    addAnnotation({
      sample_path: selectedSample.path,
      label,
      start_ms: null,
      end_ms: null,
      annotator: "user",
    });
    setStatusMsg("Label assigned");
    setTimeout(() => setStatusMsg(null), 1500);
  };

  const handleRegionCreated = (start_ms: number, end_ms: number, label: string) => {
    if (!selectedSample) return;
    addAnnotation({
      sample_path: selectedSample.path,
      label,
      start_ms,
      end_ms,
      annotator: "user",
    });
  };

  // ---------------------------------------------------------------------------
  // Playback controls
  // ---------------------------------------------------------------------------
  const handlePlayPause = () => {
    if (!wsRef.current) return;
    if (wsRef.current.isPlaying()) {
      wsRef.current.pause();
      setIsPlaying(false);
    } else {
      wsRef.current.play();
      setIsPlaying(true);
    }
  };

  const handleStop = () => {
    if (!wsRef.current) return;
    wsRef.current.stop();
    setIsPlaying(false);
  };

  // ---------------------------------------------------------------------------
  // Task 17.2: Export annotations
  // ---------------------------------------------------------------------------
  const handleExport = async () => {
    if (!selectedProject) return;
    try {
      const res = await fetch(
        apiUrl(`/projects/${encodeURIComponent(selectedProject)}/annotations/export?format=jsonl`),
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "annotations.jsonl";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setStatusMsg(`Export failed: ${e instanceof Error ? e.message : String(e)}`);
      setTimeout(() => setStatusMsg(null), 3000);
    }
  };

  // ---------------------------------------------------------------------------
  // Task 17.2: Import annotations
  // ---------------------------------------------------------------------------
  const handleImportFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file || !selectedProject) return;
    const ext = file.name.split(".").pop()?.toLowerCase() ?? "jsonl";
    const format = ext === "csv" ? "csv" : "jsonl";
    try {
      const content = await file.text();
      const res = await fetch(
        apiUrl(`/projects/${encodeURIComponent(selectedProject)}/annotations/import`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ content, format }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { imported?: number; invalid?: number };
      const imported = data.imported ?? 0;
      const invalid = data.invalid ?? 0;
      setStatusMsg(`Imported ${imported} annotations, ${invalid} invalid`);
      setTimeout(() => setStatusMsg(null), 3000);
      // Re-fetch annotations
      fetch(apiUrl(`/projects/${encodeURIComponent(selectedProject)}/annotations`))
        .then((r) => r.json())
        .then((d: Annotation[]) => setAnnotations(Array.isArray(d) ? d : []))
        .catch(() => {/* ignore */});
    } catch (err) {
      setStatusMsg(`Import failed: ${err instanceof Error ? err.message : String(err)}`);
      setTimeout(() => setStatusMsg(null), 3000);
    }
    // Reset file input so the same file can be re-imported
    if (importFileRef.current) importFileRef.current.value = "";
  };

  // ---------------------------------------------------------------------------
  // Task 17.3: Validate annotations
  // ---------------------------------------------------------------------------
  const handleValidate = async () => {
    if (!selectedProject) return;
    setValidating(true);
    try {
      const res = await fetch(
        apiUrl(`/projects/${encodeURIComponent(selectedProject)}/annotations/validate`),
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as ValidationResult;
      setValidationResult(data);
    } catch (e) {
      setStatusMsg(`Validation failed: ${e instanceof Error ? e.message : String(e)}`);
      setTimeout(() => setStatusMsg(null), 3000);
    } finally {
      setValidating(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Task 17.4: Bulk assign helpers
  // ---------------------------------------------------------------------------
  const handleToggleBulkMode = () => {
    setBulkMode((prev) => {
      if (prev) {
        // Deactivating — clear selections
        setSelectedPaths(new Set());
        setBulkLabel("");
      }
      return !prev;
    });
  };

  const handleSelectAll = () => {
    setSelectedPaths(new Set(filteredSamples.map((s) => s.path)));
  };

  const handleDeselectAll = () => {
    setSelectedPaths(new Set());
  };

  const handleTogglePath = (path: string) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) {
        next.delete(path);
      } else {
        next.add(path);
      }
      return next;
    });
  };

  const handleApplyToSelected = async () => {
    if (!selectedProject || selectedPaths.size === 0 || !bulkLabel) return;
    try {
      const res = await fetch(
        apiUrl(`/projects/${encodeURIComponent(selectedProject)}/annotations/bulk`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ paths: [...selectedPaths], label: bulkLabel }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setStatusMsg(`Bulk label "${bulkLabel}" applied to ${selectedPaths.size} samples`);
      setTimeout(() => setStatusMsg(null), 2500);
      // Refresh annotations
      const annRes = await fetch(
        apiUrl(`/projects/${encodeURIComponent(selectedProject)}/annotations`),
      );
      if (annRes.ok) {
        const data = (await annRes.json()) as Annotation[];
        setAnnotations(Array.isArray(data) ? data : []);
      }
      // Deactivate bulk mode and clear selections
      setBulkMode(false);
      setSelectedPaths(new Set());
      setBulkLabel("");
    } catch (e) {
      setStatusMsg(`Bulk assign failed: ${e instanceof Error ? e.message : String(e)}`);
      setTimeout(() => setStatusMsg(null), 3000);
    }
  };

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------
  const goToPrev = () => {
    if (selectedIndex > 0) {
      setSelectedIndex(selectedIndex - 1);
      setIsPlaying(false);
    }
  };

  const goToNext = () => {
    if (selectedIndex < filteredSamples.length - 1) {
      setSelectedIndex(selectedIndex + 1);
      setIsPlaying(false);
    }
  };

  // ---------------------------------------------------------------------------
  // Keyboard shortcuts
  // ---------------------------------------------------------------------------
  React.useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      // Only handle when annotation tab is active (component is mounted)
      const tag = (e.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      if (e.code === "Space") {
        e.preventDefault();
        handlePlayPause();
      } else if (e.code === "ArrowLeft") {
        e.preventDefault();
        goToPrev();
      } else if (e.code === "ArrowRight") {
        e.preventDefault();
        goToNext();
      } else if (/^Digit[1-9]$/.test(e.code)) {
        const n = parseInt(e.code.replace("Digit", ""), 10) - 1;
        if (taxonomy[n] && selectedSample) {
          addAnnotation({
            sample_path: selectedSample.path,
            label: taxonomy[n].label,
            start_ms: null,
            end_ms: null,
            annotator: "user",
          });
          setStatusMsg(`Label "${taxonomy[n].label}" assigned`);
          setTimeout(() => setStatusMsg(null), 1500);
        }
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIndex, filteredSamples, taxonomy, selectedSample, isPlaying]);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div className="flex h-full flex-col overflow-hidden bg-white dark:bg-secondary-900">
      {/* Top bar: project selector + progress + export/import/validate */}
      <div className="flex items-center gap-4 border-b border-secondary-200 bg-secondary-50 px-6 py-3 dark:border-secondary-700 dark:bg-secondary-800/70 flex-wrap">
        <div className="flex items-center gap-2">
          <label className="text-sm font-semibold text-secondary-700 dark:text-secondary-300">
            Project:
          </label>
          {projectsLoading ? (
            <span className="text-sm text-secondary-400">Loading…</span>
          ) : (
            <select
              value={selectedProject}
              onChange={(e) => setSelectedProject(e.target.value)}
              className="rounded-md border border-secondary-300 bg-white px-3 py-1.5 text-sm dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            >
              {projects.length === 0 && (
                <option value="">No projects</option>
              )}
              {projects.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={() => {
              setSelectedProject((prev) => {
                // Re-trigger effect by briefly clearing and restoring
                const tmp = prev;
                setSelectedProject("");
                setTimeout(() => setSelectedProject(tmp), 0);
                return "";
              });
            }}
            className="rounded-md p-1.5 text-secondary-500 hover:bg-secondary-100 dark:hover:bg-secondary-700"
            title="Refresh"
            aria-label="Refresh project data"
          >
            <RefreshCw className="h-4 w-4" />
          </button>
        </div>

        {/* Export / Import buttons (task 17.2) */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => { void handleExport(); }}
            disabled={!selectedProject}
            className="inline-flex items-center gap-1.5 rounded-md border border-secondary-300 bg-white px-3 py-1.5 text-xs font-semibold text-secondary-700 hover:bg-secondary-50 disabled:opacity-50 transition-colors dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
            title="Export annotations as JSONL"
          >
            <Download className="h-3.5 w-3.5" />
            Export
          </button>
          <button
            type="button"
            onClick={() => importFileRef.current?.click()}
            disabled={!selectedProject}
            className="inline-flex items-center gap-1.5 rounded-md border border-secondary-300 bg-white px-3 py-1.5 text-xs font-semibold text-secondary-700 hover:bg-secondary-50 disabled:opacity-50 transition-colors dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
            title="Import annotations from JSONL or CSV"
          >
            <Upload className="h-3.5 w-3.5" />
            Import
          </button>
          {/* Hidden file input for import */}
          <input
            ref={importFileRef}
            type="file"
            accept=".jsonl,.csv"
            className="hidden"
            onChange={(e) => { void handleImportFileChange(e); }}
            aria-label="Import annotations file"
          />
        </div>

        {/* Progress indicator */}
        {samples.length > 0 && (
          <div className="flex items-center gap-2 ml-auto">
            <span className="text-xs text-secondary-500 dark:text-secondary-400">
              Progress:
            </span>
            <div className="h-2 w-32 overflow-hidden rounded-full bg-secondary-200 dark:bg-secondary-700">
              <div
                className="h-full rounded-full bg-green-500 transition-all duration-300"
                style={{ width: `${(annotatedCount / samples.length) * 100}%` }}
              />
            </div>
            <span className="text-xs font-semibold text-secondary-700 dark:text-secondary-300">
              {annotatedCount} / {samples.length}
            </span>
            {/* Validate button (task 17.3) */}
            <button
              type="button"
              onClick={() => { void handleValidate(); }}
              disabled={!selectedProject || validating}
              className="inline-flex items-center gap-1.5 rounded-md border border-secondary-300 bg-white px-3 py-1.5 text-xs font-semibold text-secondary-700 hover:bg-secondary-50 disabled:opacity-50 transition-colors dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
              title="Validate annotation coverage"
            >
              {validating ? (
                <span className="inline-block h-3.5 w-3.5 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
              ) : (
                <ShieldCheck className="h-3.5 w-3.5" />
              )}
              Validate
            </button>
          </div>
        )}

        {/* Status message */}
        {statusMsg && (
          <span className="ml-2 text-xs font-semibold text-green-600 dark:text-green-400">
            {statusMsg}
          </span>
        )}
      </div>

      {/* Task 17.3: Validation report below the top bar */}
      {validationResult && (
        <div className="border-b border-secondary-200 bg-white px-6 py-3 dark:border-secondary-700 dark:bg-secondary-900">
          <div className="flex items-center gap-4 flex-wrap">
            <span className="text-xs text-secondary-500 dark:text-secondary-400">
              Total: <strong className="text-secondary-800 dark:text-secondary-200">{validationResult.total_samples}</strong>
            </span>
            <span className="text-xs text-secondary-500 dark:text-secondary-400">
              Annotated: <strong className="text-green-600 dark:text-green-400">{validationResult.annotated_count}</strong>
            </span>
            <span className="text-xs text-secondary-500 dark:text-secondary-400">
              Unannotated: <strong className={validationResult.unannotated_count === 0 ? "text-green-600 dark:text-green-400" : "text-amber-600 dark:text-amber-400"}>{validationResult.unannotated_count}</strong>
            </span>
            {validationResult.unannotated_count === 0 ? (
              <span className="inline-flex items-center gap-1 text-xs font-semibold text-green-600 dark:text-green-400">
                <CheckCircle2 className="h-4 w-4" />
                All samples annotated
              </span>
            ) : (
              <details className="text-xs">
                <summary className="inline-flex cursor-pointer items-center gap-1 font-semibold text-amber-600 dark:text-amber-400 select-none">
                  <AlertCircle className="h-4 w-4" />
                  {validationResult.unannotated_count} sample{validationResult.unannotated_count !== 1 ? "s" : ""} missing labels — click to expand
                </summary>
                <ul className="mt-2 max-h-40 overflow-y-auto rounded-md border border-amber-200 bg-amber-50 p-2 dark:border-amber-800 dark:bg-amber-900/20">
                  {validationResult.missing_labels.map((path) => (
                    <li key={path} className="truncate py-0.5 font-mono text-xs text-amber-800 dark:text-amber-300">
                      {path}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <button
              type="button"
              onClick={() => setValidationResult(null)}
              className="ml-auto text-xs text-secondary-400 hover:text-secondary-600 dark:hover:text-secondary-200"
              aria-label="Dismiss validation report"
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Main content: two-panel layout */}
      <div className="flex flex-1 min-h-0 overflow-hidden">
        {/* Left panel: sample list */}
        <div className="flex w-72 flex-shrink-0 flex-col border-r border-secondary-200 dark:border-secondary-700">
          {/* Filter + search */}
          <div className="flex flex-col gap-2 border-b border-secondary-200 p-3 dark:border-secondary-700">
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-secondary-400" />
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search samples…"
                className="w-full rounded-md border border-secondary-300 bg-white py-1.5 pl-8 pr-3 text-xs dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100 dark:placeholder-secondary-400"
              />
            </div>
            <div className="flex gap-1">
              {(["all", "unannotated", "partial"] as FilterMode[]).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setFilterMode(mode)}
                  className={`flex-1 rounded-md px-2 py-1 text-xs font-medium transition-colors capitalize ${
                    filterMode === mode
                      ? "bg-primary-600 text-white"
                      : "bg-secondary-100 text-secondary-600 hover:bg-secondary-200 dark:bg-secondary-700 dark:text-secondary-300 dark:hover:bg-secondary-600"
                  }`}
                >
                  {mode}
                </button>
              ))}
              {/* Task 17.4: Bulk toggle */}
              <button
                type="button"
                onClick={handleToggleBulkMode}
                className={`rounded-md px-2 py-1 text-xs font-medium transition-colors ${
                  bulkMode
                    ? "bg-amber-500 text-white hover:bg-amber-600"
                    : "bg-secondary-100 text-secondary-600 hover:bg-secondary-200 dark:bg-secondary-700 dark:text-secondary-300 dark:hover:bg-secondary-600"
                }`}
                title="Toggle bulk assign mode"
              >
                Bulk
              </button>
            </div>

            {/* Task 17.4: Bulk mode controls */}
            {bulkMode && (
              <div className="flex flex-col gap-2 rounded-md border border-amber-200 bg-amber-50 p-2 dark:border-amber-800 dark:bg-amber-900/20">
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={handleSelectAll}
                    className="flex-1 rounded-md bg-secondary-100 px-2 py-1 text-xs font-medium text-secondary-700 hover:bg-secondary-200 dark:bg-secondary-700 dark:text-secondary-300 dark:hover:bg-secondary-600"
                  >
                    Select All
                  </button>
                  <button
                    type="button"
                    onClick={handleDeselectAll}
                    className="flex-1 rounded-md bg-secondary-100 px-2 py-1 text-xs font-medium text-secondary-700 hover:bg-secondary-200 dark:bg-secondary-700 dark:text-secondary-300 dark:hover:bg-secondary-600"
                  >
                    Deselect All
                  </button>
                </div>
                <select
                  value={bulkLabel}
                  onChange={(e) => setBulkLabel(e.target.value)}
                  className="w-full rounded-md border border-secondary-300 bg-white px-2 py-1.5 text-xs dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
                  aria-label="Bulk label selector"
                >
                  <option value="">Select label…</option>
                  {taxonomy.length > 0 ? (
                    taxonomy.map(({ label, depth }) => (
                      <option key={label} value={label}>
                        {"  ".repeat(depth)}{label}
                      </option>
                    ))
                  ) : null}
                </select>
                {taxonomy.length === 0 && (
                  <input
                    type="text"
                    value={bulkLabel}
                    onChange={(e) => setBulkLabel(e.target.value)}
                    placeholder="Enter label…"
                    className="w-full rounded-md border border-secondary-300 bg-white px-2 py-1.5 text-xs dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
                  />
                )}
                <button
                  type="button"
                  onClick={() => { void handleApplyToSelected(); }}
                  disabled={selectedPaths.size === 0 || !bulkLabel}
                  className="w-full rounded-md bg-amber-500 px-2 py-1.5 text-xs font-semibold text-white hover:bg-amber-600 disabled:opacity-50 transition-colors"
                >
                  Apply to Selected ({selectedPaths.size})
                </button>
              </div>
            )}
          </div>

          {/* Sample list */}
          <div className="flex-1 overflow-y-auto">
            {samplesLoading ? (
              <div className="flex items-center justify-center py-8 text-secondary-400 text-sm">
                <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary-500 border-t-transparent mr-2" />
                Loading samples…
              </div>
            ) : filteredSamples.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-8 text-secondary-400 text-sm gap-2">
                <Mic className="h-8 w-8 opacity-30" />
                <span>No samples found</span>
              </div>
            ) : (
              filteredSamples.map((sample, idx) => {
                const status = getAnnotationStatus(sample.path, annotations);
                const isSelected = idx === selectedIndex;
                const isChecked = selectedPaths.has(sample.path);
                return (
                  <div
                    key={sample.path}
                    className={`flex w-full items-center gap-2 px-3 py-2.5 text-xs transition-colors border-b border-secondary-100 dark:border-secondary-700/50 ${
                      isSelected
                        ? "bg-primary-50 text-primary-800 dark:bg-primary-900/30 dark:text-primary-200"
                        : "text-secondary-700 hover:bg-secondary-50 dark:text-secondary-300 dark:hover:bg-secondary-800"
                    }`}
                  >
                    {/* Task 17.4: checkbox column in bulk mode */}
                    {bulkMode && (
                      <input
                        type="checkbox"
                        checked={isChecked}
                        onChange={() => handleTogglePath(sample.path)}
                        className="h-3.5 w-3.5 flex-shrink-0 rounded border-secondary-300 text-primary-600 focus:ring-primary-500"
                        aria-label={`Select ${sample.filename}`}
                        onClick={(e) => e.stopPropagation()}
                      />
                    )}
                    <button
                      type="button"
                      onClick={() => {
                        setSelectedIndex(idx);
                        setIsPlaying(false);
                      }}
                      className="flex flex-1 items-center gap-2 text-left min-w-0"
                    >
                      <StatusIcon status={status} />
                      <span className="flex-1 truncate font-medium">
                        {sample.filename}
                      </span>
                    </button>
                  </div>
                );
              })
            )}
          </div>
        </div>

        {/* Right panel: waveform + annotation controls */}
        <div className="flex flex-1 flex-col overflow-y-auto p-5 gap-5">
          {/* Sample header */}
          {selectedSample ? (
            <div className="flex items-center justify-between">
              <div>
                <h2 className="text-base font-bold text-secondary-900 dark:text-secondary-100">
                  {selectedSample.filename}
                </h2>
                <p className="text-xs text-secondary-500 dark:text-secondary-400 mt-0.5">
                  {selectedSample.path}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={goToPrev}
                  disabled={selectedIndex <= 0}
                  className="rounded-md border border-secondary-300 bg-white p-1.5 text-secondary-600 hover:bg-secondary-50 disabled:opacity-40 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-300"
                  title="Previous sample (←)"
                  aria-label="Previous sample"
                >
                  <ChevronLeft className="h-4 w-4" />
                </button>
                <span className="text-xs text-secondary-500">
                  {selectedIndex + 1} / {filteredSamples.length}
                </span>
                <button
                  type="button"
                  onClick={goToNext}
                  disabled={selectedIndex >= filteredSamples.length - 1}
                  className="rounded-md border border-secondary-300 bg-white p-1.5 text-secondary-600 hover:bg-secondary-50 disabled:opacity-40 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-300"
                  title="Next sample (→)"
                  aria-label="Next sample"
                >
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center flex-1 text-secondary-400 gap-3">
              <Mic className="h-12 w-12 opacity-20" />
              <p className="text-sm">Select a sample from the list to begin annotating</p>
              <p className="text-xs text-secondary-300 dark:text-secondary-500">
                Shortcuts: Space (play/pause) · ← → (prev/next) · 1–9 (assign label)
              </p>
            </div>
          )}

          {selectedSample && (
            <>
              {/* Waveform player */}
              <WaveformPlayer
                audioUrl={audioUrl}
                annotations={selectedAnnotations}
                taxonomy={taxonomy}
                onRegionCreated={handleRegionCreated}
                isPlaying={isPlaying}
                onPlayPause={handlePlayPause}
                onStop={handleStop}
                wsRef={wsRef}
              />

              {/* Whole-file label assignment */}
              <div className="rounded-lg border border-secondary-200 bg-secondary-50 p-4 dark:border-secondary-700 dark:bg-secondary-800/50">
                <h3 className="mb-3 flex items-center gap-2 text-sm font-semibold text-secondary-800 dark:text-secondary-200">
                  <Tag className="h-4 w-4" />
                  Whole-file Label
                </h3>
                <div className="flex items-center gap-2">
                  {taxonomy.length > 0 ? (
                    <select
                      value={wholeFileLabel}
                      onChange={(e) => setWholeFileLabel(e.target.value)}
                      className="flex-1 rounded-md border border-secondary-300 bg-white px-3 py-1.5 text-sm dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
                    >
                      <option value="">Select label…</option>
                      {taxonomy.map(({ label, depth }) => (
                        <option key={label} value={label}>
                          {"  ".repeat(depth)}{label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={freeTextLabel}
                      onChange={(e) => setFreeTextLabel(e.target.value)}
                      placeholder="Enter label (no taxonomy defined)"
                      className="flex-1 rounded-md border border-secondary-300 bg-white px-3 py-1.5 text-sm dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
                    />
                  )}
                  <button
                    type="button"
                    onClick={handleWholeFileLabel}
                    disabled={taxonomy.length > 0 ? !wholeFileLabel : !freeTextLabel}
                    className="rounded-lg bg-primary-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
                  >
                    Assign
                  </button>
                </div>
                {taxonomy.length > 0 && (
                  <p className="mt-1.5 text-xs text-secondary-400">
                    Tip: press 1–9 to assign the nth taxonomy label instantly
                  </p>
                )}
              </div>

              {/* Existing annotations list */}
              {selectedAnnotations.length > 0 && (
                <div className="rounded-lg border border-secondary-200 bg-white p-4 dark:border-secondary-700 dark:bg-secondary-800">
                  <h3 className="mb-3 text-sm font-semibold text-secondary-800 dark:text-secondary-200">
                    Annotations ({selectedAnnotations.length})
                  </h3>
                  <div className="flex flex-col gap-1.5">
                    {selectedAnnotations.map((ann, i) => (
                      <div
                        key={i}
                        className="flex items-center gap-2 rounded-md bg-secondary-50 px-3 py-2 text-xs dark:bg-secondary-700/50"
                      >
                        <span
                          className="h-2.5 w-2.5 rounded-full flex-shrink-0"
                          style={{ backgroundColor: REGION_COLORS[i % REGION_COLORS.length].replace("0.3", "0.8") }}
                        />
                        <span className="font-semibold text-secondary-800 dark:text-secondary-200">
                          {ann.label}
                        </span>
                        {ann.start_ms != null && ann.end_ms != null ? (
                          <span className="text-secondary-500 dark:text-secondary-400">
                            {(ann.start_ms / 1000).toFixed(2)}s – {(ann.end_ms / 1000).toFixed(2)}s
                          </span>
                        ) : (
                          <span className="text-secondary-400 italic">whole file</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

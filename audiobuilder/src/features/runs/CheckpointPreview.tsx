// audiobuilder/src/features/runs/CheckpointPreview.tsx
import React from "react";
import { Layers, Music, RefreshCw } from "lucide-react";
import { apiUrl } from "../../utils/api";

interface RunSummary {
  run_id: string;
}

interface Checkpoint {
  node_index: number;
  node_type: string;
  sample_count: number;
}

interface CheckpointSample {
  filename: string;
  label: string;
  audio_url: string;
}

interface CheckpointPreviewProps {
  runId: string | null;
}

export default function CheckpointPreview({ runId }: CheckpointPreviewProps) {
  const [resolvedRunId, setResolvedRunId] = React.useState<string | null>(null);
  const [checkpoints, setCheckpoints] = React.useState<Checkpoint[] | null>(null);
  const [selectedNodeIndex, setSelectedNodeIndex] = React.useState<number | null>(null);
  const [samples, setSamples] = React.useState<CheckpointSample[] | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [samplesLoading, setSamplesLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Resolve runId: if null, fetch /runs and take first entry
  React.useEffect(() => {
    if (runId !== null) {
      setResolvedRunId(runId);
      return;
    }

    let cancelled = false;
    fetch(apiUrl("/runs"))
      .then((r) => r.json() as Promise<RunSummary[]>)
      .then((runs) => {
        if (!cancelled) {
          setResolvedRunId(runs.length > 0 ? runs[0].run_id : null);
        }
      })
      .catch(() => {
        if (!cancelled) setResolvedRunId(null);
      });

    return () => {
      cancelled = true;
    };
  }, [runId]);

  // Fetch checkpoints when resolvedRunId changes
  React.useEffect(() => {
    if (!resolvedRunId) {
      setCheckpoints(null);
      setSelectedNodeIndex(null);
      setSamples(null);
      return;
    }

    let cancelled = false;
    setLoading(true);
    setError(null);
    setCheckpoints(null);
    setSelectedNodeIndex(null);
    setSamples(null);

    fetch(apiUrl(`/run/${resolvedRunId}/checkpoints`))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Checkpoint[]>;
      })
      .then((data) => {
        if (!cancelled) {
          setCheckpoints(data);
          if (data.length > 0) {
            setSelectedNodeIndex(data[0].node_index);
          }
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Failed to load checkpoints");
          setCheckpoints([]);
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [resolvedRunId]);

  // Fetch samples when selectedNodeIndex changes
  React.useEffect(() => {
    if (!resolvedRunId || selectedNodeIndex === null) {
      setSamples(null);
      return;
    }

    let cancelled = false;
    setSamplesLoading(true);
    setSamples(null);

    fetch(apiUrl(`/run/${resolvedRunId}/checkpoints/${selectedNodeIndex}/samples`, { n: 10 }))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<CheckpointSample[]>;
      })
      .then((data) => {
        if (!cancelled) setSamples(data);
      })
      .catch(() => {
        if (!cancelled) setSamples([]);
      })
      .finally(() => {
        if (!cancelled) setSamplesLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [resolvedRunId, selectedNodeIndex]);

  // No run available at all
  if (runId === null && resolvedRunId === null && checkpoints === null && !loading) {
    return (
      <div className="px-4 py-6 text-center text-sm text-secondary-400 dark:text-secondary-500">
        No run selected
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 px-4 py-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <Layers className="w-4 h-4 text-secondary-500 dark:text-secondary-400 shrink-0" />
        <span className="text-xs font-semibold text-secondary-700 dark:text-secondary-300">
          Checkpoint Preview
        </span>
        {resolvedRunId && (
          <span className="text-[10px] font-mono text-secondary-400 dark:text-secondary-500 ml-1">
            {resolvedRunId}
          </span>
        )}
      </div>

      {/* Loading checkpoints */}
      {loading && (
        <div className="flex items-center gap-2 text-xs text-secondary-400 dark:text-secondary-500">
          <RefreshCw className="w-3 h-3 animate-spin" />
          Loading checkpoints…
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="text-xs text-red-500 dark:text-red-400">{error}</div>
      )}

      {/* No checkpoints */}
      {!loading && checkpoints !== null && checkpoints.length === 0 && (
        <div className="text-xs text-secondary-400 dark:text-secondary-500">
          No checkpoints available
        </div>
      )}

      {/* Node selector */}
      {!loading && checkpoints !== null && checkpoints.length > 0 && (
        <div className="flex items-center gap-2">
          <label
            htmlFor="checkpoint-node-select"
            className="text-[11px] text-secondary-500 dark:text-secondary-400 shrink-0"
          >
            Node:
          </label>
          <select
            id="checkpoint-node-select"
            value={selectedNodeIndex ?? ""}
            onChange={(e) => setSelectedNodeIndex(Number(e.target.value))}
            className="text-[11px] rounded border border-secondary-200 dark:border-secondary-600 bg-white dark:bg-secondary-700 text-secondary-700 dark:text-secondary-200 px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-primary-400"
          >
            {checkpoints.map((cp) => (
              <option key={cp.node_index} value={cp.node_index}>
                {cp.node_type} ({cp.sample_count} samples)
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Samples loading */}
      {samplesLoading && (
        <div className="flex items-center gap-2 text-xs text-secondary-400 dark:text-secondary-500">
          <RefreshCw className="w-3 h-3 animate-spin" />
          Loading samples…
        </div>
      )}

      {/* Sample cards */}
      {!samplesLoading && samples !== null && samples.length > 0 && (
        <div className="grid grid-cols-1 gap-2">
          {samples.map((sample, i) => (
            <div
              key={i}
              className="rounded-lg border border-secondary-200 dark:border-secondary-700 bg-secondary-50 dark:bg-secondary-800 p-2.5 flex flex-col gap-1.5"
            >
              <div className="flex items-center gap-2 flex-wrap">
                <Music className="w-3 h-3 text-secondary-400 shrink-0" />
                <span className="text-[11px] font-mono text-secondary-700 dark:text-secondary-300 truncate flex-1">
                  {sample.filename}
                </span>
                {sample.label && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary-100 dark:bg-primary-900/30 text-primary-700 dark:text-primary-400 font-medium shrink-0">
                    {sample.label}
                  </span>
                )}
              </div>
              {/* Audio player — captions not applicable for audio-only content */}
              <audio
                controls
                src={sample.audio_url}
                className="w-full h-8"
                style={{ height: "2rem" }}
              />
            </div>
          ))}
        </div>
      )}

      {/* No samples returned */}
      {!samplesLoading && samples !== null && samples.length === 0 && selectedNodeIndex !== null && (
        <div className="text-xs text-secondary-400 dark:text-secondary-500">
          No samples available for this checkpoint
        </div>
      )}
    </div>
  );
}

import React from "react";
import {
  Database,
  Play,
  RotateCcw,
  Workflow,
  Download,
  Upload,
  Trash2,
  History,
  Hash,
  CheckCircle2,
  BookOpen,
  BookmarkPlus,
  HelpCircle,
  Keyboard,
  Settings,
  X,
  FolderOpen,
  Mic,
  ShieldCheck,
  LayoutList,
  ChevronDown,
} from "lucide-react";
import { Alert, LoadingSpinner, LogViewer, ThemeToggle } from "./components";
import DatasetManager from "./features/datasets/DatasetManager";
import ProjectManager from "./features/projects/ProjectManager";
import RunHistory from "./features/runs/RunHistory";
import CheckpointPreview from "./features/runs/CheckpointPreview";
import AnnotationUI from "./features/annotation/AnnotationUI";
import QualityDashboard from "./features/quality/QualityDashboard";
import DatasetRegistry from "./features/registry/DatasetRegistry";
import FlowCanvas from "./flow/FlowCanvas";
import { usePipelineStore } from "./store/pipeline";
import { apiUrl } from "./utils/api";
import { generateYAML } from "./utils/yaml";
import { downloadYAML, openYAMLFile } from "./utils/pipelineFile";
import TemplateLibrary from "./flow/TemplateLibrary";
import HelpSidebar from "./flow/HelpSidebar";
import SaveTemplateDialog from "./flow/SaveTemplateDialog";
import { useKeyboardShortcuts, usePreferences } from "./hooks";
import type { AutosaveData } from "./hooks";

const AUTOSAVE_KEY = "audiobuilder_canvas_autosave";

// ---------------------------------------------------------------------------
// WebhookPanel — inline settings component for webhook notifications
// ---------------------------------------------------------------------------

function WebhookPanel() {
  const [webhookUrl, setWebhookUrl] = React.useState("");
  const [webhookEvents, setWebhookEvents] = React.useState<string[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [savedMsg, setSavedMsg] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    fetch(apiUrl("/webhooks"))
      .then((r) => (r.ok ? (r.json() as Promise<{ url?: string; events?: string[] }>) : null))
      .then((data) => {
        if (data) {
          setWebhookUrl(data.url ?? "");
          setWebhookEvents(data.events ?? []);
        }
      })
      .catch(() => {/* ignore — webhooks may not be configured */})
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(apiUrl("/webhooks"), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: webhookUrl, events: webhookEvents }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setSavedMsg(true);
      setTimeout(() => setSavedMsg(false), 2000);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    try {
      await fetch(apiUrl("/webhooks/test"), { method: "POST" });
    } catch {/* ignore */}
  };

  const toggleEvent = (event: string) => {
    setWebhookEvents((prev) =>
      prev.includes(event) ? prev.filter((e) => e !== event) : [...prev, event],
    );
  };

  if (loading) {
    return <div className="text-xs text-secondary-400">Loading webhook config…</div>;
  }

  return (
    <div className="space-y-3">
      <div>
        <label
          htmlFor="webhook-url"
          className="block text-xs font-medium text-secondary-700 dark:text-secondary-300 mb-1"
        >
          Webhook URL
        </label>
        <input
          id="webhook-url"
          type="url"
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          placeholder="https://hooks.example.com/notify"
          className="w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 placeholder-secondary-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100 dark:placeholder-secondary-500"
        />
      </div>

      <div>
        <p className="text-xs font-medium text-secondary-700 dark:text-secondary-300 mb-1.5">
          Notify on
        </p>
        <div className="space-y-1.5">
          {[
            { id: "pipeline_complete", label: "Pipeline complete" },
            { id: "pipeline_failed", label: "Pipeline failed" },
          ].map(({ id, label }) => (
            <label key={id} className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={webhookEvents.includes(id)}
                onChange={() => toggleEvent(id)}
                className="h-3.5 w-3.5 rounded border-secondary-300 text-primary-600 focus:ring-primary-500"
              />
              <span className="text-sm text-secondary-700 dark:text-secondary-300">{label}</span>
            </label>
          ))}
        </div>
      </div>

      {error && (
        <p className="text-xs text-red-600 dark:text-red-400">{error}</p>
      )}

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => { void handleSave(); }}
          disabled={saving}
          className="rounded-lg bg-primary-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        {webhookUrl && (
          <button
            type="button"
            onClick={() => { void handleTest(); }}
            className="rounded-lg border border-secondary-300 bg-white px-4 py-1.5 text-xs font-semibold text-secondary-700 hover:bg-secondary-50 transition-colors dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          >
            Test
          </button>
        )}
        {savedMsg && (
          <span className="text-xs font-semibold text-green-600 dark:text-green-400">Saved ✓</span>
        )}
      </div>
    </div>
  );
}

function ProjectDropdown({ onSelect }: { onSelect: (name: string) => void }) {
  const [projects, setProjects] = React.useState<Array<{ name: string }>>([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    fetch(apiUrl("/projects"))
      .then((r) => r.json())
      .then((data) => {
        // /projects returns a plain list[dict]
        setProjects(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => {
        setLoading(false);
      });
  }, []);

  if (loading) {
    return (
      <div className="py-2 px-4 text-sm text-secondary-500 dark:text-secondary-400">
        Loading projects...
      </div>
    );
  }

  if (projects.length === 0) {
    return (
      <div className="py-2 px-4 text-sm text-secondary-500 dark:text-secondary-400">
        No projects found
      </div>
    );
  }

  return (
    <>
      {projects.map((project) => (
        <button
          key={project.name}
          type="button"
          onClick={() => onSelect(project.name)}
          className="w-full px-4 py-2 text-left text-sm text-secondary-700 hover:bg-primary-50 dark:text-secondary-200 dark:hover:bg-secondary-600"
        >
          {project.name}
        </button>
      ))}
    </>
  );
}

function useSchemas() {
  const [schemas, setSchemas] = React.useState<Record<string, unknown> | null>(
    null,
  );
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    fetch(apiUrl("/schemas"))
      .then((r) => r.json())
      .then(setSchemas)
      .catch((err) => {
        setError("Failed to fetch schemas: " + err.message);
        setSchemas({});
      });
  }, []);

  return { schemas, error };
}

export default function App() {
  const { schemas, error: schemaError } = useSchemas();
  const [view, setView] = React.useState<"projects" | "pipeline" | "datasets" | "annotation" | "quality" | "runs" | "registry">(
    "pipeline",
  );
  // Project name to pre-select when navigating from registry → projects
  const [registrySelectedProject, setRegistrySelectedProject] = React.useState<string | null>(null);
  const logs = usePipelineStore((s) => s.logs);
  const isRunning = usePipelineStore((s) => s.isRunning);
  const error = usePipelineStore((s) => s.error);
  const setError = usePipelineStore((s) => s.setError);
  const addLog = usePipelineStore((s) => s.addLog);
  const clearLogs = usePipelineStore((s) => s.clearLogs);
  const setIsRunning = usePipelineStore((s) => s.setIsRunning);
  const seed = usePipelineStore((s) => s.seed);
  const setSeed = usePipelineStore((s) => s.setSeed);
  const activeProject = usePipelineStore((s) => s.activeProject);
  const setActiveProject = usePipelineStore((s) => s.setActiveProject);
  const lastRunId = usePipelineStore((s) => s.lastRunId);
  const setLastRunId = usePipelineStore((s) => s.setLastRunId);
  const [validating, setValidating] = React.useState(false);
  const [showTemplates, setShowTemplates] = React.useState(false);
  const [showSaveTemplate, setShowSaveTemplate] = React.useState(false);
  const [showShortcuts, setShowShortcuts] = React.useState(false);
  const [showSettings, setShowSettings] = React.useState(false);
  const [showHelpSidebar, setShowHelpSidebar] = React.useState(false);
  const [showProjectDropdown, setShowProjectDropdown] = React.useState(false);
  const [templateRefreshKey, setTemplateRefreshKey] = React.useState(0);
  const [streamDone, setStreamDone] = React.useState(false);
  const [streamHadError, setStreamHadError] = React.useState(false);
  const [showCheckpointPreview, setShowCheckpointPreview] = React.useState(true);
  const flowNodes = usePipelineStore((s) => s.flowNodes);
  const selectedNodeType = usePipelineStore((s) => s.selectedNodeType);

  // Preferences persistence
  const { prefs, resetPrefs } = usePreferences();

  // Progress bar state
  const [totalNodes, setTotalNodes] = React.useState<number>(0);
  const [currentNodeIndex, setCurrentNodeIndex] = React.useState<number>(-1);
  const [currentNodeName, setCurrentNodeName] = React.useState<string>("");
  const [nodeDurations, setNodeDurations] = React.useState<number[]>([]);

  // Autosave restore prompt
  const [autosaveData, setAutosaveData] = React.useState<AutosaveData | null>(null);

  // Check for autosave on mount (after schemas load)
  React.useEffect(() => {
    if (!schemas) return;
    try {
      const raw = localStorage.getItem(AUTOSAVE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw) as AutosaveData;
      if (Array.isArray(parsed.nodes) && parsed.nodes.length > 0) {
        setAutosaveData(parsed);
      }
    } catch {
      // Ignore corrupt autosave
    }
  }, [schemas]);

  // Request browser notification permission on first load
  React.useEffect(() => {
    if (typeof Notification !== "undefined" && Notification.permission === "default") {
      void Notification.requestPermission();
    }
  }, []);

  // Ref to the FlowCanvas clear/load functions exposed via imperative handle
  const canvasRef = React.useRef<{
    clearCanvas: () => void;
    loadYAML: (yaml: string, schemas: Record<string, unknown>) => void;
    resetNodeStatuses: () => void;
    updateNodeStatus: (nodeId: string, status: "idle" | "running" | "success" | "error", errorMsg?: string) => void;
    getNodeIndexMap: (edges: Array<{id: string; source: string; target: string}>) => Map<number, string>;
  } | null>(null);

  const handleRunPipeline = async () => {
    const { flowNodes, flowEdges, nodeConfigs } = usePipelineStore.getState();

    if (flowNodes.length === 0) {
      addLog(
        "No nodes on canvas. Drag some nodes from the palette first.",
        "warning",
      );
      return;
    }

    setIsRunning(true);
    setError(null);
    clearLogs();
    addLog("Building pipeline YAML...", "info");

    // Reset progress state
    setTotalNodes(0);
    setCurrentNodeIndex(-1);
    setCurrentNodeName("");
    setNodeDurations([]);

    // Reset node statuses before starting
    canvasRef.current?.resetNodeStatuses();

    let yamlStr: string;
    try {
      yamlStr = generateYAML(flowNodes, flowEdges, nodeConfigs, seed);
      addLog("Pipeline configuration ready. Sending to server...", "info");
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to build pipeline";
      addLog(`Build error: ${message}`, "error");
      setIsRunning(false);
      return;
    }

    // Build node index map for SSE status updates
    const nodeIndexMap = canvasRef.current?.getNodeIndexMap(flowEdges) ?? new Map<number, string>();

    try {
      const response = await fetch(apiUrl("/run-stream"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml: yamlStr }),
      });

      if (!response.ok) {
        const text = await response.text();
        throw new Error(`Server error ${response.status}: ${text}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No response body from server");

      const decoder = new TextDecoder();
      let buffer = "";
      let localStreamHadError = false;
      let streamDone = false;
      let runId: string | null = null;

      const appendStreamLog = (line: string) => {
        const trimmed = line.trim();
        if (!trimmed) return;
        try {
          const event = JSON.parse(trimmed) as {
            level?: string;
            type?: string;
            message?: string;
            time?: string;
            timestamp?: string;
            node_index?: number;
            node_type?: string;
            total_nodes?: number;
            duration?: number;
            error?: string;
            run_id?: string;
          };

          // Capture run_id from the first event
          if (event.run_id && !runId) {
            runId = event.run_id;
          }

          // Terminal sentinel — pipeline finished cleanly
          if (event.type === "done") {
            streamDone = true;
            return;
          }

          // Pipeline start — capture total node count
          if (event.type === "pipeline_start" && event.total_nodes != null) {
            setTotalNodes(event.total_nodes);
            return;
          }

          // Node status events — update node visual status and progress bar
          if (event.type === "node_start" && event.node_index != null) {
            const nodeId = nodeIndexMap.get(event.node_index);
            if (nodeId) {
              canvasRef.current?.updateNodeStatus(nodeId, "running");
            }
            setCurrentNodeIndex(event.node_index);
            setCurrentNodeName(event.node_type ?? "");
            return;
          }
          if (event.type === "node_end" && event.node_index != null) {
            const nodeId = nodeIndexMap.get(event.node_index);
            if (nodeId) {
              canvasRef.current?.updateNodeStatus(nodeId, "success");
            }
            if (event.duration != null) {
              setNodeDurations((prev) => {
                const next = [...prev];
                next[event.node_index!] = event.duration!;
                return next;
              });
            }
            return;
          }
          if (event.type === "node_error" && event.node_index != null) {
            const nodeId = nodeIndexMap.get(event.node_index);
            if (nodeId) {
              canvasRef.current?.updateNodeStatus(nodeId, "error", event.error ?? event.message);
            }
          }

          const level = (event.level ?? event.type ?? "INFO").toUpperCase();
          const logType: "info" | "error" | "warning" =
            level === "ERROR"
              ? "error"
              : level === "WARNING"
                ? "warning"
                : "info";
          if (logType === "error") {
            setStreamHadError(true);
            localStreamHadError = true;
          }

          const rawTimestamp = event.timestamp ?? event.time;
          const eventTimestamp = rawTimestamp ? new Date(rawTimestamp) : undefined;
          addLog(
            event.message ?? trimmed,
            logType,
            eventTimestamp && !Number.isNaN(eventTimestamp.getTime())
              ? eventTimestamp
              : undefined,
          );
        } catch {
          addLog(trimmed, "info");
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";

        for (const line of lines) {
          appendStreamLog(line);
        }
      }
      appendStreamLog(buffer);

      setStreamDone(streamDone);
      setStreamHadError(localStreamHadError);

      if (localStreamHadError) {
        const message = "Pipeline stream reported an error.";
        setError(message);
        addLog(message, "error");
        // Browser notification on failure
        if (typeof Notification !== "undefined" && Notification.permission === "granted") {
          new Notification("Pipeline failed ✗");
        }
      } else if (streamDone) {
        addLog("Pipeline execution complete!", "success");
        // Set lastRunId for View Results button
        if (runId) {
          setLastRunId(runId);
        }
        // Browser notification on success
        if (typeof Notification !== "undefined" && Notification.permission === "granted") {
          new Notification("Pipeline complete ✓");
        }
      } else {
        addLog("Stream ended — pipeline may have completed.", "info");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Unknown error";
      addLog(`Error: ${message}`, "error");
      setError(message);
      // Browser notification on error
      if (typeof Notification !== "undefined" && Notification.permission === "granted") {
        new Notification("Pipeline failed ✗");
      }
    } finally {
      setIsRunning(false);
      // Clear progress bar when done
      setCurrentNodeIndex(-1);
      setCurrentNodeName("");
    }
  };

  const handleSavePipeline = () => {
    const { flowNodes, flowEdges, nodeConfigs } = usePipelineStore.getState();
    if (flowNodes.length === 0) {
      addLog("Nothing to save — canvas is empty.", "warning");
      return;
    }
    try {
      const yamlStr = generateYAML(flowNodes, flowEdges, nodeConfigs, seed);
      downloadYAML(yamlStr);
      addLog("Pipeline saved as pipeline.yaml", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Save failed";
      addLog(`Save error: ${message}`, "error");
    }
  };

  const handleLoadPipeline = async () => {
    const text = await openYAMLFile();
    if (!text) return;
    if (!canvasRef.current || !schemas) {
      addLog("Canvas not ready.", "warning");
      return;
    }
    try {
      canvasRef.current.loadYAML(text, schemas);
      addLog("Pipeline loaded from file.", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Load failed";
      addLog(`Load error: ${message}`, "error");
    }
  };

  const handleClearCanvas = () => {
    if (!canvasRef.current) return;
    if (!window.confirm("Clear the canvas? This cannot be undone.")) return;
    canvasRef.current.clearCanvas();
    addLog("Canvas cleared.", "info");
  };

  const handleAutosaveRestore = () => {
    if (!autosaveData || !canvasRef.current || !schemas) return;
    try {
      // Reconstruct YAML from saved state so loadYAML can parse it
      const nodes = autosaveData.nodes as Array<{ id: string; type: string; data: Record<string, unknown>; position: { x: number; y: number } }>;
      const edges = autosaveData.edges as Array<{ id: string; source: string; target: string }>;
      const configs = autosaveData.configs as Record<string, Record<string, unknown>>;
      const yamlStr = generateYAML(nodes, edges, configs, autosaveData.seed);
      canvasRef.current.loadYAML(yamlStr, schemas);
      addLog("Previous session restored.", "success");
    } catch (err) {
      addLog(`Restore failed: ${err instanceof Error ? err.message : String(err)}`, "error");
    }
    localStorage.removeItem(AUTOSAVE_KEY);
    setAutosaveData(null);
  };

  const handleAutosaveDismiss = () => {
    localStorage.removeItem(AUTOSAVE_KEY);
    setAutosaveData(null);
  };

  const handleValidatePipeline = async () => {
    const { flowNodes, flowEdges, nodeConfigs } = usePipelineStore.getState();
    if (flowNodes.length === 0) {
      addLog("Nothing to validate — canvas is empty.", "warning");
      return;
    }
    let yamlStr: string;
    try {
      yamlStr = generateYAML(flowNodes, flowEdges, nodeConfigs, seed);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to build pipeline";
      addLog(`Validation error: ${message}`, "error");
      return;
    }
    setValidating(true);
    try {
      const res = await fetch(apiUrl("/validate"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ yaml: yamlStr }),
      });
      const result = (await res.json()) as { valid: boolean; error?: string };
      if (result.valid) {
        addLog("✓ Pipeline is valid — ready to run.", "success");
      } else {
        addLog(`✗ Validation failed: ${result.error ?? "Unknown error"}`, "error");
      }
    } catch (err) {
      addLog(`Validation request failed: ${err instanceof Error ? err.message : String(err)}`, "error");
    } finally {
      setValidating(false);
    }
  };

  // Wire keyboard shortcuts — placed after handler definitions so references are valid
  useKeyboardShortcuts({
    onSave: handleSavePipeline,
    onRun: () => { if (!isRunning) void handleRunPipeline(); },
    onFocusSearch: () => {
      window.dispatchEvent(new CustomEvent("audiobuilder:focus-search"));
    },
  });

  if (!schemas) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-gradient-to-br from-primary-50 to-secondary-50 dark:from-secondary-900 dark:to-secondary-800">
        <div className="text-center">
          <LoadingSpinner size="lg" message="Loading pipeline builder..." />
        </div>
      </div>
    );
  }

  return (
    <div className="flex h-screen w-screen flex-col bg-white dark:bg-secondary-900">
      <header className="border-b border-primary-400/30 bg-gradient-to-r from-primary-700 via-primary-600 to-purple-500 px-6 py-4 shadow-xl dark:from-primary-800 dark:via-primary-700 dark:to-purple-600">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-primary-600 to-primary-700">
              <span className="text-lg font-bold text-white">▶</span>
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white">
                Audio Pipeline Builder
              </h1>
              <p className="text-xs font-medium text-primary-100">
                Visual pipeline configuration
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Seed control — pipeline tab only */}
            {view === "pipeline" && (
            <div className="flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/10 px-3 py-1.5">
              <Hash className="h-3.5 w-3.5 text-white/70" />
              <label className="text-xs text-white/80 font-medium">Seed</label>
              <input
                type="number"
                value={seed}
                onChange={(e) => {
                  const v = parseInt(e.target.value, 10);
                  if (!Number.isNaN(v)) setSeed(v);
                }}
                className="w-16 bg-transparent text-white text-xs font-mono text-center focus:outline-none border-b border-white/30 focus:border-white/70"
                title="Pipeline random seed"
              />
            </div>
            )}

            {/* Pipeline-specific actions — only shown on Pipeline tab */}
            {view === "pipeline" && (<>
            {/* Save pipeline */}
            <button
              type="button"
              onClick={handleSavePipeline}
              disabled={isRunning}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/15 px-3 py-2 text-xs font-semibold text-white transition-all hover:bg-white/25 disabled:opacity-50"
              title="Save pipeline as YAML"
            >
              <Download className="h-3.5 w-3.5" />
              Save
            </button>

            {/* Load pipeline */}
            <button
              type="button"
              onClick={() => { void handleLoadPipeline(); }}
              disabled={isRunning}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/15 px-3 py-2 text-xs font-semibold text-white transition-all hover:bg-white/25 disabled:opacity-50"
              title="Load pipeline from YAML file"
            >
              <Upload className="h-3.5 w-3.5" />
              Load
            </button>

            {/* Templates */}
            <button
              type="button"
              onClick={() => setShowTemplates(true)}
              disabled={isRunning}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/15 px-3 py-2 text-xs font-semibold text-white transition-all hover:bg-white/25 disabled:opacity-50"
              title="Load a pipeline template"
            >
              <BookOpen className="h-3.5 w-3.5" />
              Templates
            </button>

            {/* Save as Template */}
            <button
              type="button"
              onClick={() => setShowSaveTemplate(true)}
              disabled={isRunning}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/15 px-3 py-2 text-xs font-semibold text-white transition-all hover:bg-white/25 disabled:opacity-50"
              title="Save current pipeline as a template"
            >
              <BookmarkPlus className="h-3.5 w-3.5" />
              Save as Template
            </button>

            {/* Clear canvas */}
            <button
              type="button"
              onClick={handleClearCanvas}
              disabled={isRunning}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/15 px-3 py-2 text-xs font-semibold text-white transition-all hover:bg-white/25 disabled:opacity-50"
              title="Clear canvas"
            >
              <Trash2 className="h-3.5 w-3.5" />
              Clear
            </button>

            {/* Clear logs */}
            <button
              type="button"
              onClick={clearLogs}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/15 px-3 py-2 text-xs font-semibold text-white transition-all hover:bg-white/25"
            >
              <RotateCcw className="h-3.5 w-3.5" />
              Clear Logs
            </button>

            {/* Validate */}
            <button
              type="button"
              onClick={() => { void handleValidatePipeline(); }}
              disabled={isRunning || validating}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/20 bg-white/15 px-3 py-2 text-xs font-semibold text-white transition-all hover:bg-white/25 disabled:opacity-50"
              title="Validate pipeline without running"
            >
              <CheckCircle2 className="h-3.5 w-3.5" />
              {validating ? "Checking…" : "Validate"}
            </button>
            </>)}

            {/* Theme toggle — always visible */}
            <ThemeToggle />

            {/* Keyboard shortcuts help */}
            <button
              type="button"
              onClick={() => setShowShortcuts(true)}
              className="inline-flex items-center justify-center rounded-lg border border-white/20 bg-white/15 p-2 text-white transition-all hover:bg-white/25"
              title="Keyboard shortcuts"
              aria-label="Show keyboard shortcuts"
            >
              <Keyboard className="h-4 w-4" />
            </button>

            {/* Node reference help sidebar — pipeline tab only */}
            {view === "pipeline" && (
            <button
              type="button"
              onClick={() => setShowHelpSidebar(true)}
              className="inline-flex items-center justify-center rounded-lg border border-white/20 bg-white/15 p-2 text-white transition-all hover:bg-white/25"
              title="Node reference"
              aria-label="Open node reference"
            >
              <HelpCircle className="h-4 w-4" />
            </button>
            )}

            {/* Settings */}
            <button
              type="button"
              onClick={() => setShowSettings(true)}
              className="inline-flex items-center justify-center rounded-lg border border-white/20 bg-white/15 p-2 text-white transition-all hover:bg-white/25"
              title="Settings"
              aria-label="Open settings"
            >
              <Settings className="h-4 w-4" />
            </button>

            {/* Run — pipeline tab only */}
            {view === "pipeline" && (
            <button
              type="button"
              onClick={() => { void handleRunPipeline(); }}
              disabled={isRunning}
              className="inline-flex items-center gap-2 rounded-lg bg-white px-5 py-2 text-sm font-bold text-primary-700 shadow-lg transition-all hover:bg-primary-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isRunning ? (
                <>
                  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-primary-700 border-t-transparent" />
                  Running...
                </>
              ) : (
                <>
                  <Play className="h-4 w-4" />
                  Run Pipeline
                </>
              )}
            </button>
            )}
          </div>
        </div>

        {schemaError && (
          <Alert
            type="error"
            title="Connection Error"
            message={schemaError}
            onClose={() => {}}
          />
        )}
        {error && (
          <Alert
            type="error"
            title="Error"
            message={error}
            onClose={() => setError(null)}
          />
        )}
      </header>

      {/* Tab bar */}
      <div className="flex gap-2 border-b border-secondary-200 bg-secondary-50 px-6 py-2.5 dark:border-secondary-700 dark:bg-secondary-800/70">
        <button
          type="button"
          onClick={() => setView("projects")}
          className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            view === "projects"
              ? "bg-primary-600 text-white"
              : "bg-white text-secondary-700 hover:bg-secondary-100 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          }`}
        >
          <FolderOpen className="h-4 w-4" /> Projects
        </button>
        <button
          type="button"
          onClick={() => setView("pipeline")}
          className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            view === "pipeline"
              ? "bg-primary-600 text-white"
              : "bg-white text-secondary-700 hover:bg-secondary-100 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          }`}
        >
          <Workflow className="h-4 w-4" /> Pipeline
        </button>
        <button
          type="button"
          onClick={() => setView("datasets")}
          className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            view === "datasets"
              ? "bg-primary-600 text-white"
              : "bg-white text-secondary-700 hover:bg-secondary-100 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          }`}
        >
          <Database className="h-4 w-4" /> Data
        </button>
        <button
          type="button"
          onClick={() => setView("annotation")}
          className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            view === "annotation"
              ? "bg-primary-600 text-white"
              : "bg-white text-secondary-700 hover:bg-secondary-100 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          }`}
        >
          <Mic className="h-4 w-4" /> Annotate
        </button>
        <button
          type="button"
          onClick={() => setView("quality")}
          className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            view === "quality"
              ? "bg-primary-600 text-white"
              : "bg-white text-secondary-700 hover:bg-secondary-100 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          }`}
        >
          <ShieldCheck className="h-4 w-4" /> Quality
        </button>
        <button
          type="button"
          onClick={() => setView("runs")}
          className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            view === "runs"
              ? "bg-primary-600 text-white"
              : "bg-white text-secondary-700 hover:bg-secondary-100 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          }`}
        >
          <History className="h-4 w-4" /> Runs
        </button>
        <button
          type="button"
          onClick={() => setView("registry")}
          className={`inline-flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
            view === "registry"
              ? "bg-primary-600 text-white"
              : "bg-white text-secondary-700 hover:bg-secondary-100 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          }`}
        >
          <LayoutList className="h-4 w-4" /> Registry
        </button>

        {/* Active project pill */}
        <div className="ml-auto flex items-center">
          {activeProject ? (
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowProjectDropdown(!showProjectDropdown)}
                className="inline-flex items-center gap-1.5 rounded-md border border-primary-300 bg-white px-3 py-1.5 text-xs font-semibold text-primary-700 hover:bg-primary-50 dark:border-primary-600 dark:bg-secondary-700 dark:text-primary-300 dark:hover:bg-secondary-600"
              >
                <FolderOpen className="h-3.5 w-3.5" />
                {activeProject}
                <ChevronDown className="h-3.5 w-3.5" />
              </button>
              {showProjectDropdown && (
                <>
                  <div
                    className="fixed inset-0 z-40"
                    onClick={() => setShowProjectDropdown(false)}
                  />
                  <div className="absolute right-0 top-full mt-2 w-64 rounded-lg border border-primary-200 bg-white shadow-xl dark:border-primary-700 dark:bg-secondary-800 z-50">
                    <div className="max-h-64 overflow-y-auto py-1">
                      <ProjectDropdown
                        onSelect={(name) => {
                          setActiveProject(name);
                          setShowProjectDropdown(false);
                        }}
                      />
                    </div>
                  </div>
                </>
              )}
            </div>
          ) : (
            <button
              type="button"
              onClick={() => setView("projects")}
              className="inline-flex items-center gap-1.5 rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-semibold text-amber-700 hover:bg-amber-100 dark:border-amber-700 dark:bg-amber-900/20 dark:text-amber-400 dark:hover:bg-amber-900/40"
            >
              <FolderOpen className="h-3.5 w-3.5" />
              No active project
            </button>
          )}
        </div>
      </div>

      {view === "pipeline" && (
        <>
          <div className="flex flex-1 min-h-0 overflow-hidden">
            <div className="flex h-full min-h-0 flex-1 flex-col">
              <FlowCanvas schemas={schemas} ref={canvasRef} />
            </div>
          </div>

          <div className="border-t border-secondary-200 bg-gradient-to-r from-secondary-50 to-secondary-100 p-4 shadow-lg dark:border-secondary-700 dark:from-secondary-800 dark:to-secondary-900">
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-secondary-900 dark:text-secondary-100">
                Execution Log
              </h3>
              <span className="badge badge-primary text-xs">
                {logs.length} entries
              </span>
            </div>
            {/* Progress bar — visible only while running */}
            {isRunning && totalNodes > 0 && (
              <div className="mb-3">
                <div className="mb-1 flex items-center justify-between text-xs text-secondary-600 dark:text-secondary-400">
                  <span className="font-medium truncate max-w-[60%]">
                    {currentNodeName ? `Running: ${currentNodeName}` : "Starting…"}
                  </span>
                  <span>
                    {currentNodeIndex >= 0 ? `${currentNodeIndex + 1} / ${totalNodes}` : `0 / ${totalNodes}`}
                    {(() => {
                      // ETA calculation: only show after 2+ nodes have completed
                      const completedDurations = nodeDurations.filter((d) => d != null && d > 0);
                      if (completedDurations.length < 2) return null;
                      const avgDuration = completedDurations.reduce((a, b) => a + b, 0) / completedDurations.length;
                      const remaining = totalNodes - (currentNodeIndex + 1);
                      if (remaining <= 0) return null;
                      const etaSec = Math.round(avgDuration * remaining);
                      return ` · ETA ~${etaSec}s`;
                    })()}
                  </span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-secondary-200 dark:bg-secondary-700">
                  <div
                    className="h-full rounded-full bg-primary-500 transition-all duration-300"
                    style={{
                      width: `${currentNodeIndex >= 0 ? ((currentNodeIndex + 1) / totalNodes) * 100 : 0}%`,
                    }}
                  />
                </div>
              </div>
            )}
            <LogViewer logs={logs} isLoading={isRunning} />
            {/* View Results button - visible after successful run */}
            {streamDone && !streamHadError && lastRunId && (
              <div className="mt-3 flex justify-center">
                <button
                  type="button"
                  onClick={() => setView("datasets")}
                  className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 transition-colors"
                >
                  View Results →
                </button>
              </div>
            )}
            {/* Checkpoint Preview panel - visible when a run has completed */}
            {lastRunId !== null && (
              <div className="mt-3 rounded-lg border border-secondary-200 bg-white dark:border-secondary-700 dark:bg-secondary-800">
                <div className="flex items-center justify-between px-4 py-2 border-b border-secondary-200 dark:border-secondary-700">
                  <span className="text-xs font-semibold text-secondary-700 dark:text-secondary-300">
                    Checkpoint Preview
                  </span>
                  <button
                    type="button"
                    onClick={() => setShowCheckpointPreview((v) => !v)}
                    className="rounded p-0.5 text-secondary-500 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200 transition-colors"
                    aria-label={showCheckpointPreview ? "Collapse checkpoint preview" : "Expand checkpoint preview"}
                  >
                    <ChevronDown
                      className={`h-4 w-4 transition-transform duration-200 ${showCheckpointPreview ? "rotate-180" : ""}`}
                    />
                  </button>
                </div>
                {showCheckpointPreview && (
                  <CheckpointPreview runId={lastRunId} />
                )}
              </div>
            )}
          </div>
        </>
      )}

      {view === "datasets" && <DatasetManager activeProject={activeProject} />}

      {view === "runs" && (
        <div className="flex-1 overflow-hidden">
          <RunHistory
            onRerun={(configYaml) => {
              if (!canvasRef.current || !schemas) {
                return;
              }
              try {
                canvasRef.current.loadYAML(configYaml, schemas);
                setView("pipeline");
                addLog("Re-run config loaded into canvas.", "success");
              } catch (err) {
                addLog(
                  `Re-run load error: ${err instanceof Error ? err.message : String(err)}`,
                  "error",
                );
              }
            }}
          />
        </div>
      )}

      {view === "projects" && (
        <div className="flex flex-1 overflow-hidden">
          <ProjectManager
            initialProject={registrySelectedProject}
            activeProject={activeProject}
            onSetActive={setActiveProject}
          />
        </div>
      )}

      {view === "annotation" && (
        <div className="flex flex-1 overflow-hidden">
          <AnnotationUI activeProject={activeProject} />
        </div>
      )}

      {view === "quality" && (
        <div className="flex flex-1 overflow-hidden">
          <QualityDashboard activeProject={activeProject} />
        </div>
      )}

      {view === "registry" && (
        <div className="flex flex-1 overflow-hidden">
          <DatasetRegistry
            onNavigateToProject={(name) => {
              setRegistrySelectedProject(name);
              setActiveProject(name);
              setView("projects");
            }}
          />
        </div>
      )}

      {/* Autosave restore prompt */}
      {autosaveData && (
        <div
          className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 flex items-center gap-4 rounded-xl border border-primary-300 bg-white px-6 py-4 shadow-2xl dark:border-primary-600 dark:bg-secondary-800"
          role="alert"
          aria-live="polite"
        >
          <span className="text-sm font-medium text-secondary-800 dark:text-secondary-100">
            Unsaved session found. Restore previous canvas?
          </span>
          <button
            type="button"
            onClick={handleAutosaveRestore}
            className="rounded-lg bg-primary-600 px-4 py-1.5 text-xs font-semibold text-white hover:bg-primary-700 transition-colors"
          >
            Restore
          </button>
          <button
            type="button"
            onClick={handleAutosaveDismiss}
            className="rounded-lg border border-secondary-300 bg-white px-4 py-1.5 text-xs font-semibold text-secondary-700 hover:bg-secondary-50 transition-colors dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          >
            Dismiss
          </button>
        </div>
      )}

      {showTemplates && schemas && (
        <TemplateLibrary
          schemas={schemas}
          hasNodes={flowNodes.length > 0}
          refreshKey={templateRefreshKey}
          onClose={() => setShowTemplates(false)}
          onLoad={(yamlStr) => {
            if (!canvasRef.current || !schemas) return;
            try {
              canvasRef.current.loadYAML(yamlStr, schemas);
              addLog("Template loaded.", "success");
            } catch (err) {
              addLog(`Template load error: ${err instanceof Error ? err.message : String(err)}`, "error");
            }
          }}
        />
      )}

      {/* Save as Template dialog */}
      {showSaveTemplate && (
        <SaveTemplateDialog
          onClose={() => setShowSaveTemplate(false)}
          onSave={async (name, description) => {
            const { flowNodes, flowEdges, nodeConfigs } = usePipelineStore.getState();
            if (flowNodes.length === 0) {
              addLog("Nothing to save — canvas is empty.", "warning");
              return;
            }
            try {
              const yamlStr = generateYAML(flowNodes, flowEdges, nodeConfigs, seed);
              const res = await fetch(apiUrl("/templates"), {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name, yaml: yamlStr, title: name, description }),
              });
              if (!res.ok) {
                const err = await res.text();
                throw new Error(`Server error ${res.status}: ${err}`);
              }
              addLog(`Template "${name}" saved successfully.`, "success");
              setTemplateRefreshKey((k) => k + 1);
              setShowSaveTemplate(false);
            } catch (err) {
              addLog(`Save template error: ${err instanceof Error ? err.message : String(err)}`, "error");
            }
          }}
        />
      )}

      {/* Keyboard shortcuts reference modal */}
      {showShortcuts && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label="Keyboard shortcuts"
          onClick={() => setShowShortcuts(false)}
        >
          <div
            className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-secondary-800"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold text-secondary-900 dark:text-secondary-100">
                Keyboard Shortcuts
              </h2>
              <button
                type="button"
                onClick={() => setShowShortcuts(false)}
                className="rounded-lg p-1.5 text-secondary-500 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200"
                aria-label="Close shortcuts modal"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-secondary-200 dark:border-secondary-600">
                  <th className="pb-2 text-left font-semibold text-secondary-600 dark:text-secondary-400">
                    Shortcut
                  </th>
                  <th className="pb-2 text-left font-semibold text-secondary-600 dark:text-secondary-400">
                    Action
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-secondary-100 dark:divide-secondary-700">
                {[
                  { keys: "Ctrl / ⌘ + S", action: "Save pipeline as YAML" },
                  { keys: "Ctrl / ⌘ + F", action: "Focus node search" },
                  { keys: "Ctrl / ⌘ + Enter", action: "Run pipeline" },
                  { keys: "Ctrl / ⌘ + Z", action: "Undo" },
                  { keys: "Ctrl / ⌘ + Shift + Z", action: "Redo" },
                ].map(({ keys, action }) => (
                  <tr key={keys}>
                    <td className="py-2.5 pr-4">
                      <kbd className="rounded bg-secondary-100 px-2 py-0.5 font-mono text-xs text-secondary-800 dark:bg-secondary-700 dark:text-secondary-200">
                        {keys}
                      </kbd>
                    </td>
                    <td className="py-2.5 text-secondary-700 dark:text-secondary-300">
                      {action}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Settings modal */}
      {showSettings && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          aria-label="Settings"
          onClick={() => setShowSettings(false)}
        >
          <div
            className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl dark:bg-secondary-800"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-lg font-bold text-secondary-900 dark:text-secondary-100">
                Settings
              </h2>
              <button
                type="button"
                onClick={() => setShowSettings(false)}
                className="rounded-lg p-1.5 text-secondary-500 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200"
                aria-label="Close settings modal"
              >
                <X className="h-5 w-5" />
              </button>
            </div>

            <div className="space-y-4">
              {/* Current theme display */}
              <div className="rounded-lg border border-secondary-200 bg-secondary-50 px-4 py-3 dark:border-secondary-600 dark:bg-secondary-700">
                <p className="text-xs font-medium text-secondary-500 dark:text-secondary-400 uppercase tracking-wide mb-1">
                  Theme Preference
                </p>
                <p className="text-sm font-semibold text-secondary-800 dark:text-secondary-100 capitalize">
                  {prefs.theme}
                </p>
              </div>

              {/* Notifications — Webhook configuration */}
              <div className="rounded-lg border border-secondary-200 bg-secondary-50 px-4 py-3 dark:border-secondary-600 dark:bg-secondary-700">
                <p className="text-xs font-medium text-secondary-500 dark:text-secondary-400 uppercase tracking-wide mb-3">
                  Notifications
                </p>
                <WebhookPanel />
              </div>

              {/* Reset preferences */}
              <div className="pt-2 border-t border-secondary-200 dark:border-secondary-600">
                <p className="text-xs text-secondary-500 dark:text-secondary-400 mb-3">
                  Resetting preferences will clear all saved settings including theme, palette states, and filter settings.
                </p>
                <button
                  type="button"
                  onClick={() => {
                    resetPrefs();
                    setShowSettings(false);
                  }}
                  className="w-full rounded-lg border border-red-300 bg-red-50 px-4 py-2 text-sm font-semibold text-red-700 transition-colors hover:bg-red-100 dark:border-red-700 dark:bg-red-900/20 dark:text-red-400 dark:hover:bg-red-900/40"
                >
                  Reset Preferences
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
      {/* Help sidebar — node reference panel */}
      <HelpSidebar
        isOpen={showHelpSidebar}
        onClose={() => setShowHelpSidebar(false)}
        selectedNodeType={selectedNodeType}
      />
    </div>
  );
}

import React from "react";
import {
  Search,
  RefreshCw,
  GitMerge,
  Plus,
  Trash2,
  ChevronDown,
  X,
  CheckCircle2,
  Clock,
  Archive,
  FileText,
  AlertCircle,
} from "lucide-react";
import { apiUrl } from "../../utils/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface RegistryProject {
  name: string;
  status: "draft" | "in-progress" | "ready" | "archived";
  version_count: number;
  total_samples: number;
  total_duration: number; // seconds
  updated_at: string;
  versions?: string[];
}

interface MergeSource {
  project: string;
  version: string;
}

interface ProjectVersion {
  version: string;
  created_at?: string;
  sample_count?: number;
}

interface DatasetRegistryProps {
  onNavigateToProject: (name: string) => void;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_LABELS: Record<RegistryProject["status"], string> = {
  draft: "Draft",
  "in-progress": "In Progress",
  ready: "Ready",
  archived: "Archived",
};

const STATUS_COLORS: Record<RegistryProject["status"], string> = {
  draft: "bg-secondary-100 text-secondary-700 dark:bg-secondary-700 dark:text-secondary-300",
  "in-progress": "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  ready: "bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300",
  archived: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
};

const STATUS_ICONS: Record<RegistryProject["status"], React.ReactNode> = {
  draft: <FileText className="h-3 w-3" />,
  "in-progress": <Clock className="h-3 w-3" />,
  ready: <CheckCircle2 className="h-3 w-3" />,
  archived: <Archive className="h-3 w-3" />,
};

function StatusBadge({ status }: { status: RegistryProject["status"] }) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${STATUS_COLORS[status]}`}
    >
      {STATUS_ICONS[status]}
      {STATUS_LABELS[status]}
    </span>
  );
}

function formatDuration(seconds: number): string {
  if (!seconds || seconds === 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return `${h}h ${m}m`;
}

function formatDate(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Merge Dialog
// ---------------------------------------------------------------------------

interface MergeDialogProps {
  projects: RegistryProject[];
  onClose: () => void;
  onSuccess: (message: string) => void;
}

function MergeDialog({ projects, onClose, onSuccess }: MergeDialogProps) {
  const [sources, setSources] = React.useState<MergeSource[]>([{ project: "", version: "" }]);
  const [targetProject, setTargetProject] = React.useState("");
  const [targetVersion, setTargetVersion] = React.useState("");
  const [submitting, setSubmitting] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [projectVersions, setProjectVersions] = React.useState<Record<string, ProjectVersion[]>>({});

  const loadVersions = React.useCallback(async (projectName: string) => {
    if (!projectName || projectVersions[projectName]) return;
    try {
      const res = await fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/versions`));
      if (!res.ok) return;
      const data = await res.json() as ProjectVersion[];
      setProjectVersions((prev) => ({ ...prev, [projectName]: data }));
    } catch {
      // ignore
    }
  }, [projectVersions]);

  const addSource = () => {
    setSources((prev) => [...prev, { project: "", version: "" }]);
  };

  const removeSource = (idx: number) => {
    setSources((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateSource = (idx: number, field: keyof MergeSource, value: string) => {
    setSources((prev) => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value };
      return next;
    });
    if (field === "project" && value) {
      void loadVersions(value);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const validSources = sources.filter((s) => s.project && s.version);
    if (validSources.length === 0) {
      setError("Add at least one source project and version.");
      return;
    }
    if (!targetProject.trim()) {
      setError("Target project name is required.");
      return;
    }
    if (!targetVersion.trim()) {
      setError("Target version name is required.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch(apiUrl("/merge"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_versions: validSources,
          target_project: targetProject.trim(),
          target_version: targetVersion.trim(),
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Merge failed: ${text}`);
      }
      onSuccess(`Merged ${validSources.length} source(s) into ${targetProject}@${targetVersion}`);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Merge failed");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label="Merge versions"
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg rounded-xl bg-white p-6 shadow-2xl dark:bg-secondary-800 max-h-[90vh] overflow-y-auto"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="mb-5 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <GitMerge className="h-5 w-5 text-primary-600 dark:text-primary-400" />
            <h2 className="text-lg font-bold text-secondary-900 dark:text-secondary-100">
              Merge Versions
            </h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-secondary-500 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200"
            aria-label="Close merge dialog"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Source versions */}
          <div>
            <div className="mb-2 flex items-center justify-between">
              <label className="text-sm font-semibold text-secondary-700 dark:text-secondary-300">
                Source Versions
              </label>
              <button
                type="button"
                onClick={addSource}
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-primary-600 hover:bg-primary-50 dark:text-primary-400 dark:hover:bg-primary-900/20"
              >
                <Plus className="h-3.5 w-3.5" />
                Add Source
              </button>
            </div>
            <div className="space-y-2">
              {sources.map((src, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  {/* Project dropdown */}
                  <div className="relative flex-1">
                    <select
                      value={src.project}
                      onChange={(e) => updateSource(idx, "project", e.target.value)}
                      className="w-full appearance-none rounded-lg border border-secondary-300 bg-white px-3 py-2 pr-8 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
                    >
                      <option value="">Select project…</option>
                      {projects.map((p) => (
                        <option key={p.name} value={p.name}>{p.name}</option>
                      ))}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-secondary-400" />
                  </div>
                  {/* Version dropdown */}
                  <div className="relative flex-1">
                    <select
                      value={src.version}
                      onChange={(e) => updateSource(idx, "version", e.target.value)}
                      disabled={!src.project}
                      className="w-full appearance-none rounded-lg border border-secondary-300 bg-white px-3 py-2 pr-8 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 disabled:opacity-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
                    >
                      <option value="">Select version…</option>
                      {(projectVersions[src.project] ?? []).map((v) => (
                        <option key={v.version} value={v.version}>{v.version}</option>
                      ))}
                    </select>
                    <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-secondary-400" />
                  </div>
                  {/* Remove button */}
                  {sources.length > 1 && (
                    <button
                      type="button"
                      onClick={() => removeSource(idx)}
                      className="rounded-lg p-1.5 text-secondary-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                      aria-label="Remove source"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Target */}
          <div className="rounded-lg border border-secondary-200 bg-secondary-50 p-4 dark:border-secondary-600 dark:bg-secondary-700/50">
            <p className="mb-3 text-sm font-semibold text-secondary-700 dark:text-secondary-300">
              Target
            </p>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="mb-1 block text-xs font-medium text-secondary-600 dark:text-secondary-400">
                  Project Name
                </label>
                <input
                  type="text"
                  value={targetProject}
                  onChange={(e) => setTargetProject(e.target.value)}
                  placeholder="e.g. merged-dataset"
                  className="w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 placeholder-secondary-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100 dark:placeholder-secondary-500"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium text-secondary-600 dark:text-secondary-400">
                  Version Name
                </label>
                <input
                  type="text"
                  value={targetVersion}
                  onChange={(e) => setTargetVersion(e.target.value)}
                  placeholder="e.g. v1.0.0"
                  className="w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 placeholder-secondary-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100 dark:placeholder-secondary-500"
                />
              </div>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-secondary-300 bg-white px-4 py-2 text-sm font-semibold text-secondary-700 transition-colors hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-primary-700 disabled:opacity-60"
            >
              {submitting ? (
                <>
                  <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
                  Merging…
                </>
              ) : (
                <>
                  <GitMerge className="h-4 w-4" />
                  Merge
                </>
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export default function DatasetRegistry({ onNavigateToProject }: DatasetRegistryProps) {
  const [projects, setProjects] = React.useState<RegistryProject[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);
  const [successMessage, setSuccessMessage] = React.useState<string | null>(null);

  // Filters
  const [search, setSearch] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState<"all" | RegistryProject["status"]>("all");

  // Merge dialog
  const [showMerge, setShowMerge] = React.useState(false);

  const loadProjects = React.useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Try /registry first, fall back to /projects
      let res = await fetch(apiUrl(`/registry?q=${encodeURIComponent(search)}&status=${statusFilter === "all" ? "" : statusFilter}`));
      if (!res.ok) {
        res = await fetch(apiUrl("/projects"));
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json() as RegistryProject[] | { projects?: RegistryProject[] };
      // Handle both array and wrapped responses
      const list: RegistryProject[] = Array.isArray(data) ? data : (data.projects ?? []);
      setProjects(list);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load registry");
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter]);

  React.useEffect(() => {
    void loadProjects();
  }, [loadProjects]);

  // Client-side filtering (in case backend doesn't support query params)
  const filtered = React.useMemo(() => {
    return projects.filter((p) => {
      const matchesSearch = search === "" || p.name.toLowerCase().includes(search.toLowerCase());
      const matchesStatus = statusFilter === "all" || p.status === statusFilter;
      return matchesSearch && matchesStatus;
    });
  }, [projects, search, statusFilter]);

  const handleMergeSuccess = (message: string) => {
    setSuccessMessage(message);
    void loadProjects();
    setTimeout(() => setSuccessMessage(null), 5000);
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden bg-gradient-to-b from-secondary-50 to-white dark:from-secondary-900 dark:to-secondary-900">
      {/* Toolbar */}
      <div className="border-b border-secondary-200 bg-white px-6 py-4 dark:border-secondary-700 dark:bg-secondary-800">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-xl font-bold text-secondary-900 dark:text-secondary-100">
              Dataset Registry
            </h2>
            <p className="mt-0.5 text-sm text-secondary-500 dark:text-secondary-400">
              Browse and manage all dataset projects
            </p>
          </div>
          <div className="flex items-center gap-2">
            {/* Merge button */}
            <button
              type="button"
              onClick={() => setShowMerge(true)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm font-semibold text-secondary-700 transition-colors hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
            >
              <GitMerge className="h-4 w-4" />
              Merge Versions
            </button>
            {/* Refresh button */}
            <button
              type="button"
              onClick={() => void loadProjects()}
              disabled={loading}
              className="inline-flex items-center gap-1.5 rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm font-semibold text-secondary-700 transition-colors hover:bg-secondary-50 disabled:opacity-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
              aria-label="Refresh registry"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Filters row */}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          {/* Search */}
          <div className="relative flex-1 min-w-[200px] max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-secondary-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by project name…"
              className="w-full rounded-lg border border-secondary-300 bg-white py-2 pl-9 pr-3 text-sm text-secondary-900 placeholder-secondary-400 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100 dark:placeholder-secondary-500"
            />
          </div>

          {/* Status filter */}
          <div className="relative">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
              className="appearance-none rounded-lg border border-secondary-300 bg-white py-2 pl-3 pr-8 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            >
              <option value="all">All Statuses</option>
              <option value="draft">Draft</option>
              <option value="in-progress">In Progress</option>
              <option value="ready">Ready</option>
              <option value="archived">Archived</option>
            </select>
            <ChevronDown className="pointer-events-none absolute right-2 top-1/2 h-4 w-4 -translate-y-1/2 text-secondary-400" />
          </div>

          {/* Result count */}
          <span className="text-sm text-secondary-500 dark:text-secondary-400">
            {filtered.length} project{filtered.length !== 1 ? "s" : ""}
          </span>
        </div>
      </div>

      {/* Success banner */}
      {successMessage && (
        <div className="mx-6 mt-4 flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700 dark:border-green-800 dark:bg-green-900/20 dark:text-green-400">
          <CheckCircle2 className="h-4 w-4 flex-shrink-0" />
          <span>{successMessage}</span>
          <button
            type="button"
            onClick={() => setSuccessMessage(null)}
            className="ml-auto rounded p-0.5 hover:bg-green-100 dark:hover:bg-green-900/40"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="mx-6 mt-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          <AlertCircle className="h-4 w-4 flex-shrink-0" />
          <span>{error}</span>
          <button
            type="button"
            onClick={() => setError(null)}
            className="ml-auto rounded p-0.5 hover:bg-red-100 dark:hover:bg-red-900/40"
            aria-label="Dismiss error"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* Table */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {loading && projects.length === 0 ? (
          <div className="flex h-48 items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-secondary-500 dark:text-secondary-400">
              <span className="inline-block h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
              <span className="text-sm">Loading registry…</span>
            </div>
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-48 flex-col items-center justify-center gap-3 text-secondary-400 dark:text-secondary-500">
            <Search className="h-10 w-10 opacity-40" />
            <p className="text-sm font-medium">
              {projects.length === 0 ? "No projects found" : "No projects match your filters"}
            </p>
            {projects.length === 0 && (
              <p className="text-xs text-secondary-400 dark:text-secondary-500">
                Create a project in the Projects tab to get started.
              </p>
            )}
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-secondary-200 bg-white shadow-sm dark:border-secondary-700 dark:bg-secondary-800">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-secondary-200 bg-secondary-50 dark:border-secondary-700 dark:bg-secondary-700/50">
                  <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Name
                  </th>
                  <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Status
                  </th>
                  <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Versions
                  </th>
                  <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Samples
                  </th>
                  <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Duration
                  </th>
                  <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Last Updated
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-secondary-100 dark:divide-secondary-700">
                {filtered.map((project) => (
                  <tr
                    key={project.name}
                    className="cursor-pointer transition-colors hover:bg-primary-50 dark:hover:bg-primary-900/10"
                    onClick={() => onNavigateToProject(project.name)}
                    title={`Open ${project.name} in Project Manager`}
                  >
                    <td className="px-5 py-3.5 font-semibold text-secondary-900 dark:text-secondary-100">
                      {project.name}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={project.status} />
                    </td>
                    <td className="px-5 py-3.5 text-right tabular-nums text-secondary-700 dark:text-secondary-300">
                      {project.version_count ?? (project.versions?.length ?? 0)}
                    </td>
                    <td className="px-5 py-3.5 text-right tabular-nums text-secondary-700 dark:text-secondary-300">
                      {project.total_samples != null ? project.total_samples.toLocaleString() : "—"}
                    </td>
                    <td className="px-5 py-3.5 text-right tabular-nums text-secondary-700 dark:text-secondary-300">
                      {formatDuration(project.total_duration)}
                    </td>
                    <td className="px-5 py-3.5 text-right text-secondary-500 dark:text-secondary-400">
                      {formatDate(project.updated_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Merge dialog */}
      {showMerge && (
        <MergeDialog
          projects={projects}
          onClose={() => setShowMerge(false)}
          onSuccess={handleMergeSuccess}
        />
      )}
    </div>
  );
}

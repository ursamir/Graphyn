import React from "react";
import {
  Plus,
  Pencil,
  Trash2,
  Copy,
  FolderOpen,
} from "lucide-react";
import { apiUrl } from "../../utils/api";
import type { Project } from "./types";
import { StatusBadge, formatDate } from "./helpers";
import { ConfirmDialog } from "./ConfirmDialog";

// ---------------------------------------------------------------------------
// ProjectList — left-side project table with create/rename/delete/clone/status
// ---------------------------------------------------------------------------

export interface ProjectListProps {
  activeProject?: string | null;
  onSetActive?: (name: string) => void;
  onSelectProject: (project: Project) => void;
  initialProject?: string | null;
}

export function ProjectList({
  activeProject,
  onSetActive,
  onSelectProject,
  initialProject,
}: ProjectListProps) {
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  // Create dialog
  const [showCreate, setShowCreate] = React.useState(false);
  const [createName, setCreateName] = React.useState("");
  const [creating, setCreating] = React.useState(false);
  const [createError, setCreateError] = React.useState<string | null>(null);

  // Rename dialog
  const [renamingProject, setRenamingProject] = React.useState<Project | null>(null);
  const [renameValue, setRenameValue] = React.useState("");
  const [renaming, setRenaming] = React.useState(false);
  const [renameError, setRenameError] = React.useState<string | null>(null);

  // Delete dialog
  const [deletingProject, setDeletingProject] = React.useState<Project | null>(null);
  const [deleting, setDeleting] = React.useState(false);

  // Clone dialog
  const [cloningProject, setCloningProject] = React.useState<Project | null>(null);
  const [cloneName, setCloneName] = React.useState("");
  const [cloning, setCloning] = React.useState(false);
  const [cloneError, setCloneError] = React.useState<string | null>(null);

  const loadProjects = React.useCallback(() => {
    setError(null);
    fetch(apiUrl("/projects"))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Project[]>;
      })
      .then((data) => {
        setProjects(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : "Failed to load projects");
        setProjects([]);
        setLoading(false);
      });
  }, []);

  React.useEffect(() => {
    loadProjects();
  }, [loadProjects]);

  // Auto-select project when navigated from registry
  React.useEffect(() => {
    if (!initialProject || projects.length === 0) return;
    const match = projects.find((p) => p.name === initialProject);
    if (match) onSelectProject(match);
  }, [initialProject, projects, onSelectProject]);

  // Create project
  const handleCreate = async () => {
    const name = createName.trim();
    if (!name) return;
    setCreating(true);
    setCreateError(null);
    try {
      const res = await fetch(apiUrl("/projects"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        const body = (await res.json()) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setShowCreate(false);
      setCreateName("");
      loadProjects();
      if (onSetActive) {
        onSetActive(name);
      }
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setCreating(false);
    }
  };

  // Rename project
  const handleRename = async () => {
    if (!renamingProject) return;
    const newName = renameValue.trim();
    if (!newName || newName === renamingProject.name) {
      setRenamingProject(null);
      return;
    }
    setRenaming(true);
    setRenameError(null);
    try {
      const res = await fetch(apiUrl(`/projects/${encodeURIComponent(renamingProject.name)}`), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newName }),
      });
      if (!res.ok) {
        const body = (await res.json()) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setRenamingProject(null);
      setRenameValue("");
      loadProjects();
    } catch (err) {
      setRenameError(err instanceof Error ? err.message : "Rename failed");
    } finally {
      setRenaming(false);
    }
  };

  // Delete project
  const handleDelete = async (project: Project) => {
    setDeleting(true);
    try {
      const res = await fetch(apiUrl(`/projects/${encodeURIComponent(project.name)}`), {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm: project.name }),
      });
      if (!res.ok) {
        const body = (await res.json()) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setDeletingProject(null);
      loadProjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setDeleting(false);
    }
  };

  // Clone project
  const handleClone = async () => {
    if (!cloningProject) return;
    const name = cloneName.trim();
    if (!name) return;
    setCloning(true);
    setCloneError(null);
    try {
      const res = await fetch(apiUrl(`/projects/${encodeURIComponent(cloningProject.name)}/clone`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!res.ok) {
        const body = (await res.json()) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setCloningProject(null);
      setCloneName("");
      loadProjects();
    } catch (err) {
      setCloneError(err instanceof Error ? err.message : "Clone failed");
    } finally {
      setCloning(false);
    }
  };

  return (
    <div className="flex-1 overflow-auto bg-gradient-to-b from-secondary-50 to-white p-6 dark:from-secondary-900 dark:to-secondary-900">
      <div className="mx-auto max-w-5xl space-y-6">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-xl font-bold text-secondary-900 dark:text-secondary-100">
              Projects
            </h2>
            <p className="mt-0.5 text-sm text-secondary-500 dark:text-secondary-400">
              Manage dataset projects, taxonomies, contracts, and specifications.
            </p>
          </div>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-primary-700"
          >
            <Plus className="h-4 w-4" />
            New Project
          </button>
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
            {error}
          </div>
        )}

        {/* Project table */}
        {loading ? (
          <div className="flex items-center justify-center py-16 text-secondary-500">
            Loading projects…
          </div>
        ) : projects.length === 0 ? (
          <div className="rounded-xl border border-dashed border-secondary-300 bg-white p-12 text-center dark:border-secondary-700 dark:bg-secondary-800/30">
            <FolderOpen className="mx-auto mb-3 h-10 w-10 text-secondary-300 dark:text-secondary-600" />
            <p className="text-base font-semibold text-secondary-600 dark:text-secondary-400">No projects yet</p>
            <p className="mt-1 text-sm text-secondary-400 dark:text-secondary-500">
              Create your first project to get started.
            </p>
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700"
            >
              <Plus className="h-4 w-4" />
              New Project
            </button>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-secondary-200 shadow-sm dark:border-secondary-700">
            <table className="w-full text-sm">
              <thead className="bg-secondary-50 dark:bg-secondary-800">
                <tr>
                  <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Name
                  </th>
                  <th className="px-5 py-3 text-center text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Active
                  </th>
                  <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Status
                  </th>
                  <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Versions
                  </th>
                  <th className="px-5 py-3 text-left text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Last Updated
                  </th>
                  <th className="px-5 py-3 text-right text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-secondary-100 bg-white dark:divide-secondary-700 dark:bg-secondary-800/30">
                {projects.map((project) => (
                  <tr
                    key={project.name}
                    className={`cursor-pointer hover:bg-secondary-50 dark:hover:bg-secondary-800/60 ${
                      activeProject === project.name ? "bg-green-50/50 dark:bg-green-900/20" : ""
                    }`}
                    onClick={() => onSelectProject(project)}
                  >
                    <td className="px-5 py-3.5 font-semibold text-secondary-900 dark:text-secondary-100">
                      {project.name}
                    </td>
                    <td className="px-5 py-3.5 text-center">
                      {activeProject === project.name ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-green-100 px-2.5 py-1 text-xs font-semibold text-green-700 dark:bg-green-900/40 dark:text-green-300">
                          <span className="h-2 w-2 rounded-full bg-green-500 animate-pulse" />
                          Active
                        </span>
                      ) : onSetActive ? (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onSetActive(project.name);
                          }}
                          className="rounded-lg border border-secondary-200 bg-white px-2.5 py-1 text-xs font-medium text-secondary-600 hover:bg-secondary-50 hover:text-secondary-900 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-300 dark:hover:bg-secondary-600"
                          title="Set as active project"
                        >
                          Set Active
                        </button>
                      ) : null}
                    </td>
                    <td className="px-5 py-3.5">
                      <StatusBadge status={project.status} />
                    </td>
                    <td className="px-5 py-3.5 text-secondary-600 dark:text-secondary-400">
                      {project.versions.length}
                    </td>
                    <td className="px-5 py-3.5 text-secondary-600 dark:text-secondary-400">
                      {formatDate(project.updated_at)}
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <div
                        className="flex items-center justify-end gap-1"
                        onClick={(e) => e.stopPropagation()}
                      >
                        <button
                          type="button"
                          onClick={() => {
                            setRenamingProject(project);
                            setRenameValue(project.name);
                            setRenameError(null);
                          }}
                          className="rounded-lg p-1.5 text-secondary-400 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200"
                          title="Rename"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setCloningProject(project);
                            setCloneName(`${project.name}-copy`);
                            setCloneError(null);
                          }}
                          className="rounded-lg p-1.5 text-secondary-400 hover:bg-secondary-100 hover:text-secondary-700 dark:hover:bg-secondary-700 dark:hover:text-secondary-200"
                          title="Clone"
                        >
                          <Copy className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeletingProject(project)}
                          className="rounded-lg p-1.5 text-secondary-400 hover:bg-red-50 hover:text-red-600 dark:hover:bg-red-900/20 dark:hover:text-red-400"
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Create project dialog */}
      {showCreate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          onClick={() => setShowCreate(false)}
        >
          <div
            className="relative w-full max-w-sm rounded-xl bg-white p-6 shadow-2xl dark:bg-secondary-800"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-4 text-base font-bold text-secondary-900 dark:text-secondary-100">
              New Project
            </h3>
            <label className="mb-1 block text-xs font-semibold text-secondary-700 dark:text-secondary-300">
              Project Name
            </label>
            <input
              autoFocus
              type="text"
              value={createName}
              onChange={(e) => setCreateName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleCreate();
                if (e.key === "Escape") setShowCreate(false);
              }}
              placeholder="my-dataset"
              className="mb-3 w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            />
            {createError && (
              <p className="mb-3 text-xs text-red-600 dark:text-red-400">{createError}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setShowCreate(false)}
                className="rounded-lg border border-secondary-300 bg-white px-4 py-2 text-sm font-semibold text-secondary-700 hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleCreate}
                disabled={creating || !createName.trim()}
                className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-60"
              >
                {creating ? "Creating…" : "Create"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Rename dialog */}
      {renamingProject && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          onClick={() => setRenamingProject(null)}
        >
          <div
            className="relative w-full max-w-sm rounded-xl bg-white p-6 shadow-2xl dark:bg-secondary-800"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-4 text-base font-bold text-secondary-900 dark:text-secondary-100">
              Rename Project
            </h3>
            <label className="mb-1 block text-xs font-semibold text-secondary-700 dark:text-secondary-300">
              New Name
            </label>
            <input
              autoFocus
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleRename();
                if (e.key === "Escape") setRenamingProject(null);
              }}
              className="mb-3 w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            />
            {renameError && (
              <p className="mb-3 text-xs text-red-600 dark:text-red-400">{renameError}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRenamingProject(null)}
                className="rounded-lg border border-secondary-300 bg-white px-4 py-2 text-sm font-semibold text-secondary-700 hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRename}
                disabled={renaming || !renameValue.trim()}
                className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-60"
              >
                {renaming ? "Renaming…" : "Rename"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Delete confirmation dialog */}
      {deletingProject && (
        <ConfirmDialog
          title="Delete Project"
          message={`This will permanently remove "${deletingProject.name}" and all ${deletingProject.versions.length} version(s). This cannot be undone.`}
          confirmLabel={deleting ? "Deleting…" : "Delete"}
          danger
          requireTyping={deletingProject.name}
          onConfirm={() => void handleDelete(deletingProject)}
          onCancel={() => setDeletingProject(null)}
        />
      )}

      {/* Clone dialog */}
      {cloningProject && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          role="dialog"
          aria-modal="true"
          onClick={() => setCloningProject(null)}
        >
          <div
            className="relative w-full max-w-sm rounded-xl bg-white p-6 shadow-2xl dark:bg-secondary-800"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="mb-1 text-base font-bold text-secondary-900 dark:text-secondary-100">
              Clone Project
            </h3>
            <p className="mb-4 text-xs text-secondary-500 dark:text-secondary-400">
              Clones metadata, taxonomy, contract, and templates from "{cloningProject.name}". Audio files are not copied.
            </p>
            <label className="mb-1 block text-xs font-semibold text-secondary-700 dark:text-secondary-300">
              New Project Name
            </label>
            <input
              autoFocus
              type="text"
              value={cloneName}
              onChange={(e) => setCloneName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleClone();
                if (e.key === "Escape") setCloningProject(null);
              }}
              className="mb-3 w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            />
            {cloneError && (
              <p className="mb-3 text-xs text-red-600 dark:text-red-400">{cloneError}</p>
            )}
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setCloningProject(null)}
                className="rounded-lg border border-secondary-300 bg-white px-4 py-2 text-sm font-semibold text-secondary-700 hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleClone}
                disabled={cloning || !cloneName.trim()}
                className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-60"
              >
                {cloning ? "Cloning…" : "Clone"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

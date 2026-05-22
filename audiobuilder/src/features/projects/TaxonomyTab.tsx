import React from "react";
import { Plus } from "lucide-react";
import { apiUrl } from "../../utils/api";
import type { TaxonomyNode } from "./types";
import { TaxonomyNodeEditor } from "./TaxonomyNodeEditor";

// ---------------------------------------------------------------------------
// Taxonomy tab
// ---------------------------------------------------------------------------

export interface TaxonomyTabProps {
  projectName: string;
}

export function TaxonomyTab({ projectName }: TaxonomyTabProps) {
  const [tree, setTree] = React.useState<TaxonomyNode[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [success, setSuccess] = React.useState(false);

  React.useEffect(() => {
    setError(null);
    fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/taxonomy`))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<TaxonomyNode[]>;
      })
      .then((data) => {
        setTree(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => {
        setTree([]);
        setLoading(false);
      });
  }, [projectName]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/taxonomy`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(tree),
      });
      if (!res.ok) {
        const body = (await res.json()) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setSuccess(true);
      setTimeout(() => setSuccess(false), 2500);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const handleAddRoot = () => {
    setTree((prev) => [...prev, { name: "new-label", description: "", children: [] }]);
  };

  const handleUpdateRoot = (idx: number, updated: TaxonomyNode) => {
    setTree((prev) => prev.map((n, i) => (i === idx ? updated : n)));
  };

  const handleDeleteRoot = (idx: number) => {
    setTree((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleMoveRoot = (idx: number, dir: -1 | 1) => {
    setTree((prev) => {
      const next = [...prev];
      const target = idx + dir;
      if (target < 0 || target >= next.length) return prev;
      [next[idx], next[target]] = [next[target], next[idx]];
      return next;
    });
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-12 text-secondary-500">
        Loading taxonomy…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-secondary-600 dark:text-secondary-400">
          Define a hierarchical label taxonomy for this project. Double-click a label to rename it.
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleAddRoot}
            className="inline-flex items-center gap-1.5 rounded-lg border border-secondary-300 bg-white px-3 py-1.5 text-xs font-semibold text-secondary-700 hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          >
            <Plus className="h-3.5 w-3.5" /> Add Label
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-700 disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save Taxonomy"}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700 dark:border-green-800 dark:bg-green-900/20 dark:text-green-400">
          Taxonomy saved successfully.
        </div>
      )}

      <div className="rounded-lg border border-secondary-200 bg-white p-4 dark:border-secondary-700 dark:bg-secondary-800/50">
        {tree.length === 0 ? (
          <p className="text-center text-sm text-secondary-400 py-6">
            No labels defined. Click "Add Label" to get started.
          </p>
        ) : (
          tree.map((node, idx) => (
            <TaxonomyNodeEditor
              key={`root-${idx}`}
              node={node}
              depth={0}
              onUpdate={(updated) => handleUpdateRoot(idx, updated)}
              onDelete={() => handleDeleteRoot(idx)}
              onMoveUp={idx > 0 ? () => handleMoveRoot(idx, -1) : null}
              onMoveDown={idx < tree.length - 1 ? () => handleMoveRoot(idx, 1) : null}
            />
          ))
        )}
      </div>
    </div>
  );
}

import React from "react";
import { RotateCcw, History } from "lucide-react";
import { apiUrl } from "../../utils/api";
import type { Version } from "./types";
import { ConfirmDialog } from "./ConfirmDialog";
import { formatDate } from "./helpers";

// ---------------------------------------------------------------------------
// Versions tab (versions list + restore + diff + dataset card)
// ---------------------------------------------------------------------------

export interface VersionsTabProps {
  projectName: string;
}

export function VersionsTab({ projectName }: VersionsTabProps) {
  const [versions, setVersions] = React.useState<Version[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [restoring, setRestoring] = React.useState<string | null>(null);
  const [confirmRestore, setConfirmRestore] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [success, setSuccess] = React.useState<string | null>(null);

  const loadVersions = React.useCallback(() => {
    fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/versions`))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Version[]>;
      })
      .then((data) => {
        setVersions(Array.isArray(data) ? data : []);
        setLoading(false);
      })
      .catch(() => {
        setVersions([]);
        setLoading(false);
      });
  }, [projectName]);

  React.useEffect(() => {
    loadVersions();
  }, [loadVersions]);

  const handleRestore = async (version: string) => {
    setRestoring(version);
    setError(null);
    setSuccess(null);
    try {
      const res = await fetch(
        apiUrl(`/projects/${encodeURIComponent(projectName)}/versions/${encodeURIComponent(version)}/restore`),
        { method: "POST" },
      );
      if (!res.ok) {
        const body = (await res.json()) as { detail?: string };
        throw new Error(body.detail ?? `HTTP ${res.status}`);
      }
      setSuccess(`Version ${version} restored successfully.`);
      setTimeout(() => setSuccess(null), 3000);
      loadVersions();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Restore failed");
    } finally {
      setRestoring(null);
      setConfirmRestore(null);
    }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-secondary-500">Loading versions…</div>;
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-secondary-600 dark:text-secondary-400">
        Version history for this project. Restoring a version will make it the active working state.
      </p>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700 dark:border-green-800 dark:bg-green-900/20 dark:text-green-400">
          {success}
        </div>
      )}

      {versions.length === 0 ? (
        <div className="rounded-lg border border-secondary-200 bg-white p-8 text-center dark:border-secondary-700 dark:bg-secondary-800/50">
          <History className="mx-auto mb-2 h-8 w-8 text-secondary-300 dark:text-secondary-600" />
          <p className="text-sm text-secondary-500">No versions yet. Run a pipeline targeting this project to create one.</p>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-secondary-200 dark:border-secondary-700">
          <table className="w-full text-sm">
            <thead className="bg-secondary-50 dark:bg-secondary-800">
              <tr>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                  Version
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                  Created
                </th>
                <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                  Samples
                </th>
                <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-secondary-500 dark:text-secondary-400">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-secondary-100 bg-white dark:divide-secondary-700 dark:bg-secondary-800/30">
              {versions.map((v) => (
                <tr key={v.version} className="hover:bg-secondary-50 dark:hover:bg-secondary-800/60">
                  <td className="px-4 py-3 font-mono font-semibold text-secondary-800 dark:text-secondary-200">
                    {v.version}
                  </td>
                  <td className="px-4 py-3 text-secondary-600 dark:text-secondary-400">
                    {v.created_at ? formatDate(v.created_at) : "—"}
                  </td>
                  <td className="px-4 py-3 text-secondary-600 dark:text-secondary-400">
                    {v.sample_count != null ? v.sample_count.toLocaleString() : "—"}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => setConfirmRestore(v.version)}
                      disabled={restoring === v.version}
                      className="inline-flex items-center gap-1 rounded-lg border border-secondary-300 bg-white px-2.5 py-1 text-xs font-semibold text-secondary-700 hover:bg-secondary-50 disabled:opacity-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
                    >
                      <RotateCcw className="h-3.5 w-3.5" />
                      {restoring === v.version ? "Restoring…" : "Restore"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {confirmRestore && (
        <ConfirmDialog
          title="Restore Version"
          message={`Restore version "${confirmRestore}"? This will overwrite the current working state.`}
          confirmLabel="Restore"
          onConfirm={() => void handleRestore(confirmRestore)}
          onCancel={() => setConfirmRestore(null)}
        />
      )}
    </div>
  );
}

import React from "react";
import { apiUrl } from "../../utils/api";
import { SimpleMarkdown } from "./SimpleMarkdown";

// ---------------------------------------------------------------------------
// Spec tab (reads/writes spec.md)
// ---------------------------------------------------------------------------

export interface SpecTabProps {
  projectName: string;
}

export function SpecTab({ projectName }: SpecTabProps) {
  const [markdown, setMarkdown] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [success, setSuccess] = React.useState(false);
  const [preview, setPreview] = React.useState(false);

  React.useEffect(() => {
    fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/spec`))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.text();
      })
      .then((text) => {
        setMarkdown(text);
        setLoading(false);
      })
      .catch(() => {
        setMarkdown("");
        setLoading(false);
      });
  }, [projectName]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/spec`), {
        method: "PUT",
        headers: { "Content-Type": "text/plain" },
        body: markdown,
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

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-secondary-500">Loading spec…</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-secondary-600 dark:text-secondary-400">
          Write a markdown specification document for this dataset project.
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setPreview((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-secondary-300 bg-white px-3 py-1.5 text-xs font-semibold text-secondary-700 hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
          >
            {preview ? "Edit" : "Preview"}
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-700 disabled:opacity-60"
          >
            {saving ? "Saving…" : "Save Spec"}
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
          Spec saved successfully.
        </div>
      )}

      {preview ? (
        <div className="min-h-[320px] rounded-lg border border-secondary-200 bg-white p-5 dark:border-secondary-700 dark:bg-secondary-800/50">
          {markdown.trim() ? (
            <SimpleMarkdown content={markdown} />
          ) : (
            <p className="text-sm text-secondary-400 italic">Nothing to preview yet.</p>
          )}
        </div>
      ) : (
        <textarea
          value={markdown}
          onChange={(e) => setMarkdown(e.target.value)}
          rows={16}
          placeholder="# Dataset Specification&#10;&#10;Describe the purpose, design decisions, and usage of this dataset..."
          className="w-full rounded-lg border border-secondary-300 bg-white px-4 py-3 font-mono text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-800 dark:text-secondary-100"
        />
      )}
    </div>
  );
}

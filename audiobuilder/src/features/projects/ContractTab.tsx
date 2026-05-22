import React from "react";
import { X } from "lucide-react";
import { apiUrl } from "../../utils/api";
import type { Contract } from "./types";

// ---------------------------------------------------------------------------
// Contract tab
// ---------------------------------------------------------------------------

export interface ContractTabProps {
  projectName: string;
}

export function ContractTab({ projectName }: ContractTabProps) {
  const [contract, setContract] = React.useState<Contract>({});
  const [loading, setLoading] = React.useState(true);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [success, setSuccess] = React.useState(false);
  const [metaFieldInput, setMetaFieldInput] = React.useState("");

  React.useEffect(() => {
    fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/contract`))
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<Contract>;
      })
      .then((data) => {
        setContract(data ?? {});
        setLoading(false);
      })
      .catch(() => {
        setContract({});
        setLoading(false);
      });
  }, [projectName]);

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setSuccess(false);
    try {
      const res = await fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/contract`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(contract),
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

  const addMetaField = () => {
    const field = metaFieldInput.trim();
    if (!field) return;
    setContract((prev) => ({
      ...prev,
      required_metadata_fields: [...(prev.required_metadata_fields ?? []), field],
    }));
    setMetaFieldInput("");
  };

  const removeMetaField = (field: string) => {
    setContract((prev) => ({
      ...prev,
      required_metadata_fields: (prev.required_metadata_fields ?? []).filter((f) => f !== field),
    }));
  };

  if (loading) {
    return <div className="flex items-center justify-center py-12 text-secondary-500">Loading contract…</div>;
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-secondary-600 dark:text-secondary-400">
        Define technical constraints for this project. The quality checker will enforce these during validation.
      </p>

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-400">
          {error}
        </div>
      )}
      {success && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700 dark:border-green-800 dark:bg-green-900/20 dark:text-green-400">
          Contract saved successfully.
        </div>
      )}

      <div className="rounded-lg border border-secondary-200 bg-white p-5 dark:border-secondary-700 dark:bg-secondary-800/50">
        <div className="grid gap-4 sm:grid-cols-2">
          {/* Sample rate */}
          <div>
            <label className="mb-1 block text-xs font-semibold text-secondary-700 dark:text-secondary-300">
              Required Sample Rate (Hz)
            </label>
            <input
              type="number"
              value={contract.required_sample_rate ?? ""}
              onChange={(e) =>
                setContract((prev) => ({
                  ...prev,
                  required_sample_rate: e.target.value ? parseInt(e.target.value, 10) : undefined,
                }))
              }
              placeholder="e.g. 16000"
              className="w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            />
          </div>

          {/* Channels */}
          <div>
            <label className="mb-1 block text-xs font-semibold text-secondary-700 dark:text-secondary-300">
              Required Channels
            </label>
            <select
              value={contract.required_channels ?? ""}
              onChange={(e) =>
                setContract((prev) => ({
                  ...prev,
                  required_channels: e.target.value ? (parseInt(e.target.value, 10) as 1 | 2) : undefined,
                }))
              }
              className="w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            >
              <option value="">Any</option>
              <option value="1">1 (Mono)</option>
              <option value="2">2 (Stereo)</option>
            </select>
          </div>

          {/* Min duration */}
          <div>
            <label className="mb-1 block text-xs font-semibold text-secondary-700 dark:text-secondary-300">
              Min Duration (ms)
            </label>
            <input
              type="number"
              value={contract.min_duration_ms ?? ""}
              onChange={(e) =>
                setContract((prev) => ({
                  ...prev,
                  min_duration_ms: e.target.value ? parseFloat(e.target.value) : undefined,
                }))
              }
              placeholder="e.g. 500"
              className="w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            />
          </div>

          {/* Max duration */}
          <div>
            <label className="mb-1 block text-xs font-semibold text-secondary-700 dark:text-secondary-300">
              Max Duration (ms)
            </label>
            <input
              type="number"
              value={contract.max_duration_ms ?? ""}
              onChange={(e) =>
                setContract((prev) => ({
                  ...prev,
                  max_duration_ms: e.target.value ? parseFloat(e.target.value) : undefined,
                }))
              }
              placeholder="e.g. 5000"
              className="w-full rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            />
          </div>
        </div>

        {/* Required metadata fields */}
        <div className="mt-4">
          <label className="mb-1 block text-xs font-semibold text-secondary-700 dark:text-secondary-300">
            Required Metadata Fields
          </label>
          <div className="flex gap-2">
            <input
              type="text"
              value={metaFieldInput}
              onChange={(e) => setMetaFieldInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  addMetaField();
                }
              }}
              placeholder="e.g. speaker_id"
              className="flex-1 rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm text-secondary-900 focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-100"
            />
            <button
              type="button"
              onClick={addMetaField}
              className="rounded-lg border border-secondary-300 bg-white px-3 py-2 text-sm font-semibold text-secondary-700 hover:bg-secondary-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200 dark:hover:bg-secondary-600"
            >
              Add
            </button>
          </div>
          {(contract.required_metadata_fields ?? []).length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(contract.required_metadata_fields ?? []).map((field) => (
                <span
                  key={field}
                  className="inline-flex items-center gap-1 rounded-full bg-primary-100 px-2.5 py-0.5 text-xs font-medium text-primary-700 dark:bg-primary-900/40 dark:text-primary-300"
                >
                  {field}
                  <button
                    type="button"
                    onClick={() => removeMetaField(field)}
                    className="ml-0.5 rounded-full hover:text-primary-900 dark:hover:text-primary-100"
                    aria-label={`Remove ${field}`}
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="flex justify-end">
        <button
          type="button"
          onClick={handleSave}
          disabled={saving}
          className="inline-flex items-center gap-1.5 rounded-lg bg-primary-600 px-4 py-2 text-sm font-semibold text-white hover:bg-primary-700 disabled:opacity-60"
        >
          {saving ? "Saving…" : "Save Contract"}
        </button>
      </div>
    </div>
  );
}

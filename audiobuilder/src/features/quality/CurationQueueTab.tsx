import React from "react";
import { CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { apiUrl } from "../../utils/api";
import type { Finding, CurationDecision } from "./types";
import { SeverityBadge, Card, SectionTitle } from "./components";

// ---------------------------------------------------------------------------
// Curation Queue Tab
// ---------------------------------------------------------------------------

export function CurationQueueTab({
  projectName,
  findings,
}: {
  projectName: string;
  findings: Finding[];
}) {
  const [decisions, setDecisions] = React.useState<Record<string, "accepted" | "rejected">>({});
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [selected, setSelected] = React.useState<Finding | null>(null);

  // Fetch existing curation decisions whenever projectName changes
  React.useEffect(() => {
    if (!projectName) return;
    setLoading(true);
    setError(null);
    fetch(apiUrl(`/projects/${encodeURIComponent(projectName)}/curation`))
      .then((r) => (r.ok ? (r.json() as Promise<CurationDecision[]>) : []))
      .then((curData) => {
        const map: Record<string, "accepted" | "rejected"> = {};
        for (const d of curData) {
          map[d.sample_path] = d.decision;
        }
        setDecisions(map);
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Failed to load curation decisions");
      })
      .finally(() => setLoading(false));
  }, [projectName]);

  const handleDecision = async (finding: Finding, decision: "accepted" | "rejected") => {
    setSaving(finding.sample_path);
    try {
      const res = await fetch(
        apiUrl(`/projects/${encodeURIComponent(projectName)}/curation`),
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sample_path: finding.sample_path, decision }),
        },
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setDecisions((prev) => ({ ...prev, [finding.sample_path]: decision }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save decision");
    } finally {
      setSaving(null);
    }
  };

  // Only show error-severity findings in the curation queue
  const errorFindings = findings.filter((f) => f.severity === "error");
  const pending = errorFindings.filter((f) => !decisions[f.sample_path]);
  const reviewed = errorFindings.filter((f) => !!decisions[f.sample_path]);

  return (
    <div className="flex h-full min-h-0 gap-4">
      {/* Left: sample list */}
      <div className="flex w-72 shrink-0 flex-col gap-2 overflow-y-auto">
        {error && (
          <div className="rounded-lg border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-700 dark:bg-red-900/20 dark:text-red-300">
            {error}
          </div>
        )}

        {loading && (
          <div className="flex items-center justify-center py-8 text-secondary-500">
            <Loader2 className="h-5 w-5 animate-spin" />
          </div>
        )}

        {!loading && errorFindings.length === 0 && (
          <div className="py-8 text-center text-xs text-secondary-500">
            No flagged samples. Run quality checks first.
          </div>
        )}

        {pending.length > 0 && (
          <div>
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-secondary-500">
              Pending ({pending.length})
            </p>
            <div className="space-y-1">
              {pending.map((f) => (
                <button
                  key={f.sample_path}
                  type="button"
                  onClick={() => setSelected(f)}
                  className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition-colors ${
                    selected?.sample_path === f.sample_path
                      ? "border-primary-400 bg-primary-50 dark:border-primary-600 dark:bg-primary-900/20"
                      : "border-secondary-200 bg-white hover:bg-secondary-50 dark:border-secondary-700 dark:bg-secondary-800 dark:hover:bg-secondary-700"
                  }`}
                >
                  <div className="truncate font-mono text-secondary-800 dark:text-secondary-200">
                    {f.sample_path.split("/").pop()}
                  </div>
                  <div className="mt-0.5 text-secondary-500">{f.check_name}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        {reviewed.length > 0 && (
          <div className="mt-2">
            <p className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-secondary-500">
              Reviewed ({reviewed.length})
            </p>
            <div className="space-y-1">
              {reviewed.map((f) => (
                <div
                  key={f.sample_path}
                  className="flex items-center justify-between rounded-lg border border-secondary-200 bg-secondary-50 px-3 py-2 dark:border-secondary-700 dark:bg-secondary-800/50"
                >
                  <span className="truncate font-mono text-xs text-secondary-600 dark:text-secondary-400">
                    {f.sample_path.split("/").pop()}
                  </span>
                  {decisions[f.sample_path] === "accepted" ? (
                    <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-green-500" />
                  ) : (
                    <XCircle className="h-3.5 w-3.5 shrink-0 text-red-500" />
                  )}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Right: detail panel */}
      <div className="flex min-w-0 flex-1 flex-col gap-3">
        {selected ? (
          <>
            <Card>
              <div className="mb-2 flex items-start justify-between gap-2">
                <div>
                  <p className="break-all font-mono text-sm font-semibold text-secondary-900 dark:text-secondary-100">
                    {selected.sample_path.split("/").pop()}
                  </p>
                  <p className="mt-0.5 break-all text-xs text-secondary-500">
                    {selected.sample_path}
                  </p>
                </div>
                <SeverityBadge severity={selected.severity} />
              </div>
              <div className="rounded-lg bg-secondary-50 px-3 py-2 text-xs text-secondary-700 dark:bg-secondary-700/50 dark:text-secondary-300">
                <strong>{selected.check_name}:</strong> {selected.detail}
              </div>
            </Card>

            {/* Audio preview */}
            <Card>
              <SectionTitle>Audio Preview</SectionTitle>
              <audio
                controls
                src={apiUrl(`/files/${selected.sample_path.split("/").map(encodeURIComponent).join("/")}`)}
                className="w-full"
                aria-label={`Audio preview for ${selected.sample_path}`}
              />
            </Card>

            {/* Accept / Reject */}
            <div className="flex gap-2">
              <button
                type="button"
                disabled={saving === selected.sample_path}
                onClick={() => void handleDecision(selected, "accepted")}
                className={`inline-flex flex-1 items-center justify-center gap-2 rounded-lg border px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-50 ${
                  decisions[selected.sample_path] === "accepted"
                    ? "border-green-500 bg-green-500 text-white"
                    : "border-green-400 bg-white text-green-700 hover:bg-green-50 dark:bg-secondary-800 dark:text-green-400 dark:hover:bg-green-900/20"
                }`}
              >
                {saving === selected.sample_path ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <CheckCircle2 className="h-4 w-4" />
                )}
                Accept
              </button>
              <button
                type="button"
                disabled={saving === selected.sample_path}
                onClick={() => void handleDecision(selected, "rejected")}
                className={`inline-flex flex-1 items-center justify-center gap-2 rounded-lg border px-4 py-2 text-sm font-semibold transition-colors disabled:opacity-50 ${
                  decisions[selected.sample_path] === "rejected"
                    ? "border-red-500 bg-red-500 text-white"
                    : "border-red-400 bg-white text-red-700 hover:bg-red-50 dark:bg-secondary-800 dark:text-red-400 dark:hover:bg-red-900/20"
                }`}
              >
                {saving === selected.sample_path ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <XCircle className="h-4 w-4" />
                )}
                Reject
              </button>
            </div>
          </>
        ) : (
          <div className="flex flex-1 items-center justify-center text-sm text-secondary-500">
            Select a sample from the list to review.
          </div>
        )}
      </div>
    </div>
  );
}

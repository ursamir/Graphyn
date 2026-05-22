// audiobuilder/src/features/datasets/DatasetStats.tsx
// Shows split counts and per-label distribution for a generated dataset.

import React from "react";
import { BarChart3 } from "lucide-react";
import { apiUrl } from "../../utils/api";

interface DatasetStatsData {
  project: string;
  version: string;
  total: number;
  splits: Record<string, Record<string, number>>;
}

const SPLIT_COLORS: Record<string, string> = {
  train: "bg-blue-500",
  val: "bg-purple-500",
  test: "bg-green-500",
};

function splitColor(split: string) {
  return SPLIT_COLORS[split] ?? "bg-secondary-400";
}

interface DatasetStatsProps {
  project: string;
  version: string;
}

export default function DatasetStats({ project, version }: DatasetStatsProps) {
  const [stats, setStats] = React.useState<DatasetStatsData | null>(null);
  const [error, setError] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    fetch(apiUrl("/dataset-stats", { project, version }))
      .then((r) => {
        if (!r.ok) throw new Error("not found");
        return r.json() as Promise<DatasetStatsData>;
      })
      .then((data) => {
        if (!cancelled) setStats(data);
      })
      .catch(() => {
        if (!cancelled) setError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [project, version]);

  if (error || !stats) return null;

  const splitEntries = Object.entries(stats.splits).sort(([a], [b]) => {
    const order = ["train", "val", "test"];
    return (order.indexOf(a) ?? 99) - (order.indexOf(b) ?? 99);
  });

  // Collect all unique labels across splits
  const allLabels = Array.from(
    new Set(splitEntries.flatMap(([, labels]) => Object.keys(labels))),
  ).sort();

  return (
    <div className="rounded-2xl border border-secondary-200 bg-white dark:border-secondary-700 dark:bg-secondary-900 p-5 shadow-sm">
      <div className="flex items-center gap-2 mb-4">
        <BarChart3 className="w-4 h-4 text-primary-600 dark:text-primary-400" />
        <h3 className="text-sm font-bold text-secondary-900 dark:text-secondary-100">
          Dataset Statistics
        </h3>
        <span className="ml-auto text-xs text-secondary-500 dark:text-secondary-400">
          {stats.total.toLocaleString()} total samples
        </span>
      </div>

      {/* Split summary pills */}
      <div className="flex flex-wrap gap-2 mb-5">
        {splitEntries.map(([split, labels]) => {
          const count = Object.values(labels).reduce((s, n) => s + n, 0);
          const pct = stats.total > 0 ? Math.round((count / stats.total) * 100) : 0;
          return (
            <div
              key={split}
              className="flex items-center gap-2 rounded-full border border-secondary-200 dark:border-secondary-700 bg-secondary-50 dark:bg-secondary-800 px-3 py-1.5"
            >
              <span className={`w-2 h-2 rounded-full ${splitColor(split)}`} />
              <span className="text-xs font-semibold text-secondary-800 dark:text-secondary-200 capitalize">
                {split}
              </span>
              <span className="text-xs text-secondary-500 dark:text-secondary-400">
                {count.toLocaleString()} ({pct}%)
              </span>
            </div>
          );
        })}
      </div>

      {/* Label distribution table */}
      {allLabels.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-secondary-200 dark:border-secondary-700">
                <th className="text-left py-1.5 pr-4 font-semibold text-secondary-600 dark:text-secondary-400 uppercase tracking-wide">
                  Label
                </th>
                {splitEntries.map(([split]) => (
                  <th
                    key={split}
                    className="text-right py-1.5 px-3 font-semibold text-secondary-600 dark:text-secondary-400 uppercase tracking-wide capitalize"
                  >
                    {split}
                  </th>
                ))}
                <th className="text-right py-1.5 pl-3 font-semibold text-secondary-600 dark:text-secondary-400 uppercase tracking-wide">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {allLabels.map((label) => {
                const rowTotal = splitEntries.reduce(
                  (s, [, labels]) => s + (labels[label] ?? 0),
                  0,
                );
                return (
                  <tr
                    key={label}
                    className="border-b border-secondary-100 dark:border-secondary-800 last:border-0"
                  >
                    <td className="py-1.5 pr-4 font-medium text-secondary-800 dark:text-secondary-200">
                      {label}
                    </td>
                    {splitEntries.map(([split, labels]) => (
                      <td
                        key={split}
                        className="text-right py-1.5 px-3 text-secondary-600 dark:text-secondary-400 tabular-nums"
                      >
                        {(labels[label] ?? 0).toLocaleString()}
                      </td>
                    ))}
                    <td className="text-right py-1.5 pl-3 font-semibold text-secondary-800 dark:text-secondary-200 tabular-nums">
                      {rowTotal.toLocaleString()}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

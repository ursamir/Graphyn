import React from "react";
import { ChevronDown, ChevronRight, FolderOpen, Music2 } from "lucide-react";
import { buildAudioSourceUrl } from "./utils";
import type { AudioRow } from "./types";

interface AudioFolderCardProps {
  title: string;
  path: string;
  count: number;
  items: AudioRow[];
  subtitle?: string;
  source: "generated" | "input";
}

export default function AudioFolderCard({
  title,
  path,
  count,
  items,
  subtitle,
  source,
}: AudioFolderCardProps) {
  const [expanded, setExpanded] = React.useState(false);
  const previewLimit = expanded ? items.length : Math.min(items.length, 2);
  const visibleItems = items.slice(0, previewLimit);
  const hiddenCount = items.length - visibleItems.length;

  return (
    <article className="rounded-2xl border border-secondary-200 bg-white/90 shadow-sm transition-shadow hover:shadow-md dark:border-secondary-700 dark:bg-secondary-800/90">
      <div className="border-b border-secondary-100 p-4 dark:border-secondary-700/70 sm:p-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-secondary-500">
              <FolderOpen className="h-3.5 w-3.5" />
              {source === "generated" ? "Export folder" : "Input folder"}
            </div>
            <h4 className="mt-2 truncate text-base font-semibold text-secondary-900 dark:text-secondary-100">
              {title}
            </h4>
            {subtitle && (
              <p className="mt-1 text-sm text-secondary-500 dark:text-secondary-400">
                {subtitle}
              </p>
            )}
            <p className="mt-2 break-all text-xs text-secondary-500 dark:text-secondary-400">
              {path}
            </p>
          </div>
          <div className="shrink-0 rounded-2xl border border-secondary-200 bg-secondary-50 px-3 py-2 text-right dark:border-secondary-700 dark:bg-secondary-900/70">
            <div className="text-[11px] uppercase tracking-wide text-secondary-500">
              Files
            </div>
            <div className="text-lg font-bold text-secondary-900 dark:text-secondary-100">
              {count}
            </div>
          </div>
        </div>
      </div>

      <div className="space-y-3 p-4 sm:p-5">
        {visibleItems.map((item) => (
          <div
            key={item.path}
            className="rounded-xl border border-secondary-200 bg-secondary-50/70 p-3 dark:border-secondary-700 dark:bg-secondary-900/50"
          >
            <div className="mb-2 flex items-center justify-between gap-3 text-xs text-secondary-500 dark:text-secondary-400">
              <span className="truncate">
                {item.label}
                {item.split ? ` · ${item.split}` : ""}
              </span>
              <Music2 className="h-3.5 w-3.5 shrink-0" />
            </div>
            <audio
              controls
              controlsList="nodownload noplaybackrate"
              src={buildAudioSourceUrl(item.path, source)}
              className="w-full"
            />
          </div>
        ))}

        {hiddenCount > 0 && (
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="inline-flex items-center gap-2 text-sm font-medium text-primary-700 hover:text-primary-800 dark:text-primary-300 dark:hover:text-primary-200"
          >
            {expanded ? (
              <>
                <ChevronDown className="h-4 w-4" />
                Show fewer files
              </>
            ) : (
              <>
                <ChevronRight className="h-4 w-4" />
                Show {hiddenCount} more file{hiddenCount === 1 ? "" : "s"}
              </>
            )}
          </button>
        )}
      </div>
    </article>
  );
}

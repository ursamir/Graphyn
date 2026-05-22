import { FolderOpen, Layers3 } from "lucide-react";
import AudioFolderCard from "./AudioFolderCard";
import type {
  GeneratedSplitGroup,
  GroupedLabel,
  DatasetMode,
} from "./types";

interface DatasetResultsProps {
  datasetType: DatasetMode;
  project: string;
  version: string;
  inputLabel: string;
  generatedGroups: GeneratedSplitGroup[];
  inputGroups: GroupedLabel[];
  activeDataCount: number;
  hasLoadedSources: boolean;
}

export default function DatasetResults({
  datasetType,
  project,
  version,
  inputLabel,
  generatedGroups,
  inputGroups,
  activeDataCount,
  hasLoadedSources,
}: DatasetResultsProps) {
  if (!hasLoadedSources) {
    return (
      <section className="rounded-3xl border border-dashed border-secondary-300 bg-white/80 p-10 text-center text-secondary-500 shadow-sm dark:border-secondary-700 dark:bg-secondary-900/80 dark:text-secondary-400">
        No dataset sources are available yet.
      </section>
    );
  }

  if (activeDataCount === 0) {
    return (
      <section className="rounded-3xl border border-dashed border-secondary-300 bg-white/80 p-10 text-center text-secondary-500 shadow-sm dark:border-secondary-700 dark:bg-secondary-900/80 dark:text-secondary-400">
        No files matched the selected project, version, label, or search term.
      </section>
    );
  }

  if (datasetType === "generated") {
    return (
      <>
        {generatedGroups.map((splitGroup) => (
          <section
            key={splitGroup.split}
            className="overflow-hidden rounded-3xl border border-secondary-200 bg-white/80 shadow-lg dark:border-secondary-800 dark:bg-secondary-900/80"
          >
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-secondary-200 px-5 py-4 dark:border-secondary-800 sm:px-6">
              <div>
                <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.2em] text-secondary-500">
                  <Layers3 className="h-4 w-4" />
                  {splitGroup.split}
                </div>
                <p className="mt-1 text-sm text-secondary-500 dark:text-secondary-400">
                  {splitGroup.total} file{splitGroup.total === 1 ? "" : "s"} across{" "}
                  {splitGroup.labels.length} label folder
                  {splitGroup.labels.length === 1 ? "" : "s"}
                </p>
              </div>
              <div className="rounded-full border border-secondary-200 bg-secondary-50 px-3 py-1 text-xs font-semibold text-secondary-600 dark:border-secondary-700 dark:bg-secondary-950/50 dark:text-secondary-300">
                {project || "project"} / {version || "version"}
              </div>
            </div>
            <div className="grid gap-4 p-5 sm:grid-cols-2 sm:p-6 2xl:grid-cols-3">
              {splitGroup.labels.map((group) => (
                <AudioFolderCard
                  key={group.key}
                  source="generated"
                  title={group.title}
                  subtitle={`Split: ${splitGroup.split}`}
                  path={`workspace/datasets/output/${project || "project"}/${version || "version"}/${splitGroup.split}/${group.title}`}
                  count={group.count}
                  items={group.items}
                />
              ))}
            </div>
          </section>
        ))}
      </>
    );
  }

  return (
    <section className="overflow-hidden rounded-3xl border border-secondary-200 bg-white/80 shadow-lg dark:border-secondary-800 dark:bg-secondary-900/80">
      <div className="flex items-center justify-between gap-3 border-b border-secondary-200 px-5 py-4 dark:border-secondary-800 sm:px-6">
        <div>
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-[0.2em] text-secondary-500">
            <FolderOpen className="h-4 w-4" />
            Input folders
          </div>
          <p className="mt-1 text-sm text-secondary-500 dark:text-secondary-400">
            {inputGroups.length} folder{inputGroups.length === 1 ? "" : "s"} inside{" "}
            workspace/datasets/input
          </p>
        </div>
        <div className="rounded-full border border-secondary-200 bg-secondary-50 px-3 py-1 text-xs font-semibold text-secondary-600 dark:border-secondary-700 dark:bg-secondary-950/50 dark:text-secondary-300">
          {inputLabel || "all labels"}
        </div>
      </div>
      <div className="grid gap-4 p-5 sm:grid-cols-2 sm:p-6 2xl:grid-cols-3">
        {inputGroups.map((group) => (
          <AudioFolderCard
            key={group.key}
            source="input"
            title={group.title}
            path={group.path}
            count={group.count}
            items={group.items}
          />
        ))}
      </div>
    </section>
  );
}

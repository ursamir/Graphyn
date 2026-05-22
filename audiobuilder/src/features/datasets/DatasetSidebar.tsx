import { FolderOpen, Search } from "lucide-react";
import { Input, Select, Card } from "../../components";
import type {
  DatasetMode,
  DatasetSummary,
  InputLabelSummary,
} from "./types";

interface DatasetSidebarProps {
  datasetType: DatasetMode;
  datasets: DatasetSummary[];
  inputLabels: InputLabelSummary[];
  project: string;
  version: string;
  inputLabel: string;
  searchTerm: string;
  currentVersions: string[];
  activeRootPath: string;
  onProjectChange: (project: string) => void;
  onVersionChange: (version: string) => void;
  onInputLabelChange: (label: string) => void;
  onSearchTermChange: (value: string) => void;
}

export default function DatasetSidebar({
  datasetType,
  datasets,
  inputLabels,
  project,
  version,
  inputLabel,
  searchTerm,
  currentVersions,
  activeRootPath,
  onProjectChange,
  onVersionChange,
  onInputLabelChange,
  onSearchTermChange,
}: DatasetSidebarProps) {
  return (
    <aside className="space-y-4 self-start xl:sticky xl:top-6">
      <Card>
        <div className="flex items-center gap-2 text-sm font-semibold text-secondary-900 dark:text-secondary-100">
          <Search className="h-4 w-4 text-secondary-500" />
          Browse
        </div>
        <p className="mt-1 text-sm text-secondary-500 dark:text-secondary-400">
          Pick a dataset and filter the visible folders.
        </p>

        <div className="mt-4 space-y-3">
          {datasetType === "generated" ? (
            <>
              <Select
                label="Project"
                value={project}
                onChange={(e) => onProjectChange(e.target.value)}
                options={datasets.map((dataset) => ({
                  value: dataset.project,
                  label: dataset.project,
                }))}
              />

              <Select
                label="Version"
                value={version}
                onChange={(e) => onVersionChange(e.target.value)}
                options={currentVersions.map((value) => ({
                  value,
                  label: value,
                }))}
              />
            </>
          ) : (
            <Select
              label="Input label"
              value={inputLabel}
              onChange={(e) => onInputLabelChange(e.target.value)}
              options={inputLabels.map((label) => ({
                value: label.label,
                label: `${label.label} (${label.file_count})`,
              }))}
            />
          )}

          <Input
            label="Search"
            value={searchTerm}
            onChange={(e) => onSearchTermChange(e.target.value)}
            placeholder="Filter by label or path"
          />
        </div>
      </Card>

      <Card>
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-secondary-900 dark:text-secondary-100">
              Selected path
            </h3>
            <p className="mt-1 text-xs text-secondary-500 dark:text-secondary-400">
              Makes the folder structure explicit.
            </p>
          </div>
          <FolderOpen className="h-5 w-5 text-primary-600" />
        </div>
        <div className="mt-4 rounded-2xl border border-dashed border-secondary-300 bg-secondary-50 p-4 dark:border-secondary-700 dark:bg-secondary-950/40">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-secondary-500">
            Root
          </div>
          <div className="mt-2 break-all text-sm font-medium text-secondary-900 dark:text-secondary-100">
            {activeRootPath}
          </div>
        </div>
      </Card>
    </aside>
  );
}

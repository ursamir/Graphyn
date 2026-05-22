/**
 * QualityDashboard — Statistics, Quality Checks, and Curation Queue
 *
 * Uses inline SVG for charts (no external chart library required).
 * Requirements: 16, 17, 18, 19
 */
import React from "react";
import { Loader2 } from "lucide-react";
import { apiUrl } from "../../utils/api";
import type { Project, Finding, QualityTab } from "./types";
import { StatisticsTab } from "./StatisticsTab";
import { QualityChecksTab } from "./QualityChecksTab";
import { CurationQueueTab } from "./CurationQueueTab";
import { ExportGateBanner } from "./ExportGateBanner";
import { QualityReportExport } from "./QualityReportExport";

// ---------------------------------------------------------------------------
// Main QualityDashboard component
// ---------------------------------------------------------------------------

export default function QualityDashboard({ activeProject }: { activeProject?: string | null } = {}) {
  const [projects, setProjects] = React.useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = React.useState<string>("");
  const [selectedVersion, setSelectedVersion] = React.useState<string>("");
  const [versions, setVersions] = React.useState<string[]>([]);
  const [activeTab, setActiveTab] = React.useState<QualityTab>("statistics");
  const [loadingProjects, setLoadingProjects] = React.useState(false);
  const [lastCheckFindings, setLastCheckFindings] = React.useState<Finding[]>([]);
  const [bannerRefreshKey, setBannerRefreshKey] = React.useState(0);

  // Task 18.1: Sync activeProject prop → selectedProject state
  React.useEffect(() => {
    if (activeProject) setSelectedProject(activeProject);
  }, [activeProject]);

  // Clear findings when project changes to avoid stale curation data
  React.useEffect(() => {
    setLastCheckFindings([]);
    setBannerRefreshKey((k) => k + 1);
  }, [selectedProject]);

  // Load projects on mount
  React.useEffect(() => {
    setLoadingProjects(true);
    fetch(apiUrl("/projects"))
      .then((r) => (r.ok ? (r.json() as Promise<Project[]>) : []))
      .then((data) => {
        setProjects(data);
        if (data.length > 0 && !activeProject) {
          setSelectedProject(data[0].name);
        }
      })
      .catch(() => setProjects([]))
      .finally(() => setLoadingProjects(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Load versions when project changes
  React.useEffect(() => {
    if (!selectedProject) {
      setVersions([]);
      setSelectedVersion("");
      return;
    }
    fetch(apiUrl(`/projects/${encodeURIComponent(selectedProject)}/versions`))
      .then((r) => (r.ok ? (r.json() as Promise<Array<{ version: string } | string>>) : []))
      .then((data) => {
        const vList = data.map((v) => (typeof v === "string" ? v : v.version));
        setVersions(vList);
        setSelectedVersion(vList.length > 0 ? vList[vList.length - 1] : "");
      })
      .catch(() => {
        setVersions([]);
        setSelectedVersion("");
      });
  }, [selectedProject]);

  const tabs: { id: QualityTab; label: string }[] = [
    { id: "statistics", label: "Statistics" },
    { id: "checks", label: "Quality Checks" },
    { id: "curation", label: "Curation Queue" },
  ];

  return (
    <div className="flex h-full w-full flex-col overflow-hidden bg-secondary-50 dark:bg-secondary-900">
      {/* Top bar: project + version selectors */}
      <div className="flex flex-wrap items-center gap-3 border-b border-secondary-200 bg-white px-6 py-3 dark:border-secondary-700 dark:bg-secondary-800">
        <div className="flex items-center gap-2">
          <label
            htmlFor="qd-project-select"
            className="text-xs font-semibold text-secondary-600 dark:text-secondary-400"
          >
            Project
          </label>
          {loadingProjects ? (
            <Loader2 className="h-4 w-4 animate-spin text-secondary-400" />
          ) : (
            <select
              id="qd-project-select"
              value={selectedProject}
              onChange={(e) => setSelectedProject(e.target.value)}
              className="rounded-lg border border-secondary-300 bg-white px-2.5 py-1.5 text-sm text-secondary-800 focus:outline-none focus:ring-2 focus:ring-primary-500 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200"
            >
              {projects.length === 0 && <option value="">No projects</option>}
              {projects.map((p) => (
                <option key={p.name} value={p.name}>
                  {p.name}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="flex items-center gap-2">
          <label
            htmlFor="qd-version-select"
            className="text-xs font-semibold text-secondary-600 dark:text-secondary-400"
          >
            Version
          </label>
          <select
            id="qd-version-select"
            value={selectedVersion}
            onChange={(e) => setSelectedVersion(e.target.value)}
            disabled={versions.length === 0}
            className="rounded-lg border border-secondary-300 bg-white px-2.5 py-1.5 text-sm text-secondary-800 focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50 dark:border-secondary-600 dark:bg-secondary-700 dark:text-secondary-200"
          >
            {versions.length === 0 && <option value="">No versions</option>}
            {versions.map((v) => (
              <option key={v} value={v}>
                {v}
              </option>
            ))}
          </select>
        </div>

        <div className="ml-auto">
          <QualityReportExport projectName={selectedProject} version={selectedVersion} />
        </div>
      </div>

      {/* Export gate banner */}
      {selectedProject && (
        <div className="px-6 pt-3">
          <ExportGateBanner projectName={selectedProject} refreshKey={bannerRefreshKey} />
        </div>
      )}

      {/* Inner tab bar */}
      <div className="flex gap-1 border-b border-secondary-200 bg-white px-6 py-2 dark:border-secondary-700 dark:bg-secondary-800">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? "bg-primary-600 text-white"
                : "text-secondary-600 hover:bg-secondary-100 dark:text-secondary-300 dark:hover:bg-secondary-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="flex-1 overflow-auto px-6 py-4">
        {activeTab === "statistics" && (
          <StatisticsTab projectName={selectedProject} version={selectedVersion} />
        )}
        {activeTab === "checks" && (
          <QualityChecksTab
            projectName={selectedProject}
            onCheckComplete={(findings) => {
              setLastCheckFindings(findings);
              setBannerRefreshKey((k) => k + 1);
            }}
          />
        )}
        {activeTab === "curation" && (
          <CurationQueueTab projectName={selectedProject} findings={lastCheckFindings} />
        )}
      </div>
    </div>
  );
}

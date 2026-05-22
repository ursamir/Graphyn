import React from "react";
import { ChevronRight, Tag, FileText, ClipboardList, History } from "lucide-react";
import type { Project, ProjectTab } from "./types";
import { StatusBadge } from "./helpers";
import { ProjectList } from "./ProjectList";
import { TaxonomyTab } from "./TaxonomyTab";
import { ContractTab } from "./ContractTab";
import { SpecTab } from "./SpecTab";
import { VersionsTab } from "./VersionsTab";

// ---------------------------------------------------------------------------
// Project detail panel (tabs)
// ---------------------------------------------------------------------------

interface ProjectDetailProps {
  project: Project;
  onBack: () => void;
}

function ProjectDetail({ project, onBack }: ProjectDetailProps) {
  const [activeTab, setActiveTab] = React.useState<ProjectTab>("taxonomy");

  const tabs: { id: ProjectTab; label: string; icon: React.ReactNode }[] = [
    { id: "taxonomy", label: "Taxonomy", icon: <Tag className="h-4 w-4" /> },
    { id: "contract", label: "Contract", icon: <ClipboardList className="h-4 w-4" /> },
    { id: "spec", label: "Spec", icon: <FileText className="h-4 w-4" /> },
    { id: "versions", label: "Versions", icon: <History className="h-4 w-4" /> },
  ];

  return (
    <div className="space-y-4">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onBack}
          className="text-sm font-medium text-primary-600 hover:text-primary-700 dark:text-primary-400 dark:hover:text-primary-300"
        >
          Projects
        </button>
        <ChevronRight className="h-4 w-4 text-secondary-400" />
        <span className="text-sm font-semibold text-secondary-800 dark:text-secondary-200">
          {project.name}
        </span>
        <StatusBadge status={project.status} />
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-secondary-200 dark:border-secondary-700">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={`inline-flex items-center gap-1.5 rounded-t-md px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? "border-b-2 border-primary-600 text-primary-700 dark:text-primary-400"
                : "text-secondary-600 hover:text-secondary-800 dark:text-secondary-400 dark:hover:text-secondary-200"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div>
        {activeTab === "taxonomy" && <TaxonomyTab projectName={project.name} />}
        {activeTab === "contract" && <ContractTab projectName={project.name} />}
        {activeTab === "spec" && <SpecTab projectName={project.name} />}
        {activeTab === "versions" && <VersionsTab projectName={project.name} />}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main ProjectManager component
// ---------------------------------------------------------------------------

export default function ProjectManager({
  initialProject,
  activeProject,
  onSetActive,
}: {
  initialProject?: string | null;
  activeProject?: string | null;
  onSetActive?: (name: string) => void;
} = {}) {
  const [selectedProject, setSelectedProject] = React.useState<Project | null>(null);

  if (selectedProject) {
    return (
      <div className="flex-1 overflow-auto bg-gradient-to-b from-secondary-50 to-white p-6 dark:from-secondary-900 dark:to-secondary-900">
        <div className="mx-auto max-w-4xl">
          <ProjectDetail project={selectedProject} onBack={() => setSelectedProject(null)} />
        </div>
      </div>
    );
  }

  return (
    <ProjectList
      activeProject={activeProject}
      onSetActive={onSetActive}
      onSelectProject={setSelectedProject}
      initialProject={initialProject}
    />
  );
}

// ---------------------------------------------------------------------------
// ProjectManager — shared types
// ---------------------------------------------------------------------------

export interface Project {
  name: string;
  status: "draft" | "in-progress" | "ready" | "archived";
  created_at: string;
  updated_at: string;
  versions: string[];
}

export interface TaxonomyNode {
  name: string;
  description?: string;
  children: TaxonomyNode[];
}

export interface Contract {
  required_sample_rate?: number;
  required_channels?: 1 | 2;
  min_duration_ms?: number;
  max_duration_ms?: number;
  required_metadata_fields?: string[];
}

export interface Version {
  version: string;
  created_at?: string;
  sample_count?: number;
}

export type ProjectTab = "list" | "taxonomy" | "contract" | "spec" | "versions";

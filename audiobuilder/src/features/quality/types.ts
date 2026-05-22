// ---------------------------------------------------------------------------
// QualityDashboard — shared types
// ---------------------------------------------------------------------------

export interface Project {
  name: string;
  status: string;
  versions: string[];
}

export interface Stats {
  total_samples: number;
  total_duration_s: number;
  label_distribution: Record<string, number>;
  duration_histogram: { bin: string; count: number }[];
  sample_rate_distribution: Record<string, number>;
  snr_histogram: { bin: string; count: number }[];
  class_imbalance_warning?: boolean;
  imbalanced_labels?: string[];
}

export interface Finding {
  sample_path: string;
  check_name: string;
  severity: "error" | "warning";
  detail: string;
}

export interface CheckJob {
  job_id: string;
  status: "running" | "completed" | "failed";
  findings: Finding[];
}

export interface ExportGate {
  can_export: boolean;
  blocking_issues: Finding[];
}

export interface CurationDecision {
  sample_path: string;
  decision: "accepted" | "rejected";
  timestamp: string;
}

export type QualityTab = "statistics" | "checks" | "curation";

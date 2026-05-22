export type DatasetMode = "generated" | "input";

export interface DatasetSummary {
  project: string;
  versions: string[];
}

export interface AudioRow {
  path: string;
  split?: string;
  label: string;
}

export interface InputLabelSummary {
  label: string;
  file_count: number;
}

export interface GroupedLabel {
  key: string;
  title: string;
  path: string;
  count: number;
  items: AudioRow[];
}

export interface GeneratedSplitGroup {
  split: string;
  total: number;
  labels: GroupedLabel[];
}

